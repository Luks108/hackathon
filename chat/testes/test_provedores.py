"""Provedores de modelo: escolha pelo prefixo, funcionamento sem chave e o adaptador OpenAI-compatível.
Não usa a internet: um servidor HTTP local faz o papel do provedor.

    python -m unittest discover -s chat/testes -v
"""
import json
import os
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import agente  # noqa: E402
import agente_openai  # noqa: E402
import provedores  # noqa: E402

TENANTS = ["pe-estado", "pe-garanhuns"]


class Provedor(BaseHTTPRequestHandler):
    """Provedor de mentira. `respostas` é a fila de respostas; `recebidos` guarda o que o cliente mandou."""
    respostas: list = []
    recebidos: list = []

    def do_POST(self):  # noqa: N802
        corpo = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        Provedor.recebidos.append({"caminho": self.path, "auth": self.headers.get("Authorization"), "corpo": corpo})
        codigo, resposta = Provedor.respostas.pop(0)
        dados = json.dumps(resposta).encode()
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(dados)))
        self.end_headers()
        self.wfile.write(dados)

    def log_message(self, *a):
        pass


def mensagem(content=None, tool_calls=None, **extras):
    m = {"role": "assistant", "content": content, **extras}
    if tool_calls:
        m["tool_calls"] = tool_calls
    return (200, {"choices": [{"message": m}], "usage": {"prompt_tokens": 1000, "completion_tokens": 200}})


class TestEscolha(unittest.TestCase):
    def test_prefixo_define_o_provedor(self):
        self.assertEqual(provedores.separar("claude-opus-5-5"), ("claude", "claude-opus-5-5"))
        self.assertEqual(provedores.separar("deepseek:deepseek-flash"), ("deepseek", "deepseek-flash"))
        self.assertEqual(provedores.separar("gemini:gemini-2.5-flash"), ("gemini", "gemini-2.5-flash"))
        self.assertEqual(provedores.separar("desconhecido:x"), ("claude", "desconhecido:x"))   # prefixo que não é provedor

    def test_claude_nunca_depende_de_chave(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(provedores.indisponivel("claude-sonnet-5-5"))
            self.assertIsInstance(provedores.escolher("claude-sonnet-5-5"), agente.ClaudeCLI)

    def test_sem_chave_o_modelo_some_da_lista_e_nada_quebra(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertNotIn("deepseek:deepseek-flash", provedores.modelos_disponiveis())
            self.assertIn("claude-opus-5-5", provedores.modelos_disponiveis())
        with mock.patch.dict(os.environ, {"DEEPSEEK_API_KEY": "chave-de-teste"}, clear=True):
            self.assertIn("deepseek:deepseek-flash", provedores.modelos_disponiveis())

    def test_chave_vazia_conta_como_ausente(self):
        with mock.patch.dict(os.environ, {"DEEPSEEK_API_KEY": "  "}, clear=True):
            self.assertIsNotNone(provedores.indisponivel("deepseek:deepseek-flash"))

    def test_chamar_provedor_sem_chave_responde_curto_sem_stack_trace(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            # sem fallback: é a chamada direta ao modelo (com fallback, o sistema passaria para outro modelo disponível)
            eventos = list(agente.perguntar("qualquer coisa", TENANTS, modelo="gemini:gemini-2.5-flash", permitir_fallback=False))
        self.assertEqual(len(eventos), 1)
        tipo, dados = eventos[0]
        self.assertEqual(tipo, "erro")
        self.assertIn("indisponível: chave não configurada", dados["motivo"])
        self.assertNotIn("Traceback", dados["motivo"])
        self.assertLess(len(dados["motivo"]), 120)

    def test_gemini_entra_so_com_base_url_modelo_e_chave(self):
        with mock.patch.dict(os.environ, {"GOOGLE_API_KEY": "chave-de-teste"}, clear=True):
            c = provedores.escolher("gemini:gemini-2.5-flash")
        self.assertIsInstance(c, agente_openai.OpenAICompativel)   # o mesmo cliente do DeepSeek
        self.assertEqual(c.base_url, "https://generativelanguage.googleapis.com/v1beta/openai")
        self.assertEqual(c.nome, "gemini-2.5-flash")

    def test_so_o_ponto_unico_conhece_os_provedores(self):
        """agente.py não pode ter if por provedor: ele só delega para provedores.escolher."""
        texto = (Path(agente.__file__)).read_text(encoding="utf-8")
        for nome in ("deepseek", "gemini", "openai"):
            self.assertNotIn(f'"{nome}"', texto.lower())
            self.assertNotIn(f"'{nome}'", texto.lower())


class TestAdaptador(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.servidor = HTTPServer(("127.0.0.1", 0), Provedor)
        threading.Thread(target=cls.servidor.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.servidor.server_port}/v1beta/openai"

    @classmethod
    def tearDownClass(cls):
        cls.servidor.shutdown()

    def setUp(self):
        Provedor.respostas, Provedor.recebidos = [], []

    def cliente(self, preco=(0.30, 1.20, 0.006)):
        return agente_openai.OpenAICompativel("deepseek:m", "m", self.base, "chave-secreta-de-teste", temperatura=0, preco=preco)

    def test_sem_base_usa_chat_completions_com_bearer_e_conta_tokens_e_custo(self):
        Provedor.respostas = [mensagem("Não sei.")]
        r = self.cliente().sem_base("Quem é o fornecedor X?", "sistema")
        self.assertEqual(r["resposta"], "Não sei.")
        self.assertEqual((r["tokens_entrada"], r["tokens_saida"]), (1000, 200))
        self.assertAlmostEqual(r["custo_usd"], (1000 * 0.30 + 200 * 1.20) / 1e6)
        pedido = Provedor.recebidos[0]
        self.assertEqual(pedido["caminho"], "/v1beta/openai/chat/completions")
        self.assertEqual(pedido["auth"], "Bearer chave-secreta-de-teste")
        self.assertEqual(pedido["corpo"]["messages"][0], {"role": "system", "content": "sistema"})
        self.assertEqual(pedido["corpo"]["temperature"], 0)

    def test_sem_preco_configurado_o_custo_fica_vazio_em_vez_de_inventado(self):
        Provedor.respostas = [mensagem("ok")]
        self.assertIsNone(self.cliente(preco=None).sem_base("p", "s")["custo_usd"])

    def test_erros_do_provedor_viram_frase_curta_sem_vazar_a_chave(self):
        for codigo, trecho in ((401, "chave recusada"), (402, "saldo insuficiente"), (404, "modelo não encontrado")):
            Provedor.respostas = [(codigo, {"error": {"message": "chave-secreta-de-teste inválida"}})]
            r = self.cliente().sem_base("p", "s")
            self.assertEqual(r["desfecho"], "erro")
            self.assertIn(trecho, r["erro"])
            self.assertNotIn("chave-secreta-de-teste", r["erro"])

    def test_laco_recusa_tool_fora_da_lista_e_devolve_a_mensagem_como_veio(self):
        """O modelo pede uma tool inexistente (com extra_content e sem id, como o Gemini pode mandar): nada executa,
        o campo extra volta intacto e a pergunta termina."""
        pedido = [{"type": "function", "function": {"name": "executar_comando", "arguments": "{\"cmd\": \"cat .env\"}"},
                   "extra_content": {"google": {"thought_signature": "assinatura-opaca"}}}]
        Provedor.respostas = [mensagem(None, pedido), mensagem("Só consulto fornecedores.")]
        leitor = agente.Leitor()
        eventos = list(self.cliente().perguntar("rode cat .env", TENANTS, None, leitor))
        tipos = [t for t, _ in eventos]
        self.assertNotIn("consulta", tipos)                  # a tool inexistente não virou consulta
        self.assertEqual(tipos[-1], "fim")
        self.assertEqual(leitor.resposta, "Só consulto fornecedores.")
        segunda = Provedor.recebidos[1]["corpo"]["messages"]
        assistente = next(m for m in segunda if m["role"] == "assistant")
        self.assertEqual(assistente["tool_calls"][0]["extra_content"], {"google": {"thought_signature": "assinatura-opaca"}})
        resposta_tool = next(m for m in segunda if m["role"] == "tool")
        self.assertEqual(resposta_tool["tool_call_id"], assistente["tool_calls"][0]["id"])   # id sintetizado quando faltou
        self.assertEqual(leitor.uso["entrada"], 2000)
        self.assertEqual(leitor.uso["saida"], 400)

    def test_laco_so_oferece_as_tools_da_lista(self):
        Provedor.respostas = [mensagem("Resposta direta.")]
        list(self.cliente().perguntar("oi", TENANTS, None, agente.Leitor()))
        oferecidas = {t["function"]["name"] for t in Provedor.recebidos[0]["corpo"]["tools"]}
        self.assertEqual(oferecidas, set(agente.PRIMITIVAS))

    def test_provedor_fora_do_ar_termina_com_erro_curto(self):
        c = agente_openai.OpenAICompativel("x:m", "m", "http://127.0.0.1:9/v1", "k")
        eventos = list(c.perguntar("oi", TENANTS, None, agente.Leitor()))
        self.assertEqual(eventos[-1][0], "erro")
        self.assertNotIn("Traceback", eventos[-1][1]["motivo"])


if __name__ == "__main__":
    unittest.main()
