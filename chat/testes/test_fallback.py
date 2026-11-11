"""Fallback entre provedores: a cadeia, as três travas (texto já dito, pergunta inválida, orçamento de tempo) e o log do worker.
Não usa a internet nem gasta token: os clientes são falsos e o relógio é simulado.

    python -m unittest discover -s chat/testes -v
"""
import importlib
import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import agente  # noqa: E402
import provedores  # noqa: E402

TENANTS = ["pe-estado", "pe-garanhuns"]
CHAVES = {"DEEPSEEK_API_KEY": "chave-de-teste"}     # só para o deepseek não ser pulado; nunca é enviada a lugar nenhum


class Falso:
    """Cliente de mentira. `roteiro` = eventos que ele emite, na ordem. Um número vale como "gastou tantos segundos"."""

    def __init__(self, roteiro, relogio=None):
        self.roteiro, self.relogio, self.limites, self.chamado = roteiro, relogio, [], 0

    def perguntar(self, texto, tenants, historico, leitor, limite_s=None):
        self.chamado += 1
        self.limites.append(limite_s)
        for item in self.roteiro:
            if isinstance(item, (int, float)):
                self.relogio[0] += item
                continue
            if isinstance(item, Exception):
                raise item
            tipo, dados = item
            if tipo == "texto":
                leitor.resposta += dados["delta"]
            elif tipo == "consulta":
                leitor.consultas.append(dados["nome"])
            yield tipo, dados


def texto(t):
    return [("consulta", {"nome": "buscar"}), ("texto", {"delta": t}), ("fim", {"duracao_ms": 5})]


def erro(m):
    return [("erro", {"motivo": m})]


def rodar(clientes, **kw):
    """Roda agente.perguntar com `clientes` (modelo -> Falso). Devolve (eventos, leitor)."""
    leitor = agente.Leitor()
    with mock.patch.object(provedores, "escolher", side_effect=lambda m: clientes[m]), \
            mock.patch.object(provedores, "cadeia", side_effect=lambda m: list(clientes)):
        eventos = list(agente.perguntar("pergunta", TENANTS, leitor=leitor, modelo=next(iter(clientes)), **kw))
    return eventos, leitor


def tipos(eventos):
    return [t for t, _ in eventos]


class TestCadeia(unittest.TestCase):
    def test_pedido_primeiro_depois_a_ordem_padrao(self):
        with mock.patch.dict(os.environ, CHAVES, clear=True):
            self.assertEqual(provedores.cadeia("claude-opus-5-5"), ["claude-opus-5-5", "deepseek:deepseek-flash", "claude-sonnet-5-5"])

    def test_sem_repetidos(self):
        with mock.patch.dict(os.environ, CHAVES, clear=True):
            self.assertEqual(provedores.cadeia("claude-sonnet-5-5"), ["claude-sonnet-5-5", "deepseek:deepseek-flash"])

    def test_indisponivel_sai_da_cadeia(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(provedores.cadeia("claude-opus-5-5"), ["claude-opus-5-5", "claude-sonnet-5-5"])

    def test_pedido_indisponivel_cede_o_lugar_ao_proximo_disponivel(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(provedores.cadeia("gemini:gemini-2.5-flash"), ["claude-sonnet-5-5"])

    def test_nunca_vazia(self):
        ordem = {"AGENTE_FALLBACK_ORDEM": "gemini:x,openai:y"}
        with mock.patch.dict(os.environ, ordem, clear=True):
            self.assertEqual(provedores.cadeia("deepseek:deepseek-flash"), ["deepseek:deepseek-flash"])

    def test_ordem_pela_variavel_de_ambiente_e_nenhum_desliga(self):
        with mock.patch.dict(os.environ, {**CHAVES, "AGENTE_FALLBACK_ORDEM": " claude-sonnet-5-5 , deepseek:deepseek-v4-pro "}, clear=True):
            self.assertEqual(provedores.cadeia("claude-opus-5-5"), ["claude-opus-5-5", "claude-sonnet-5-5", "deepseek:deepseek-v4-pro"])
        with mock.patch.dict(os.environ, {**CHAVES, "AGENTE_FALLBACK_ORDEM": "nenhum"}, clear=True):
            self.assertEqual(provedores.cadeia("claude-opus-5-5"), ["claude-opus-5-5"])


class TestTroca(unittest.TestCase):
    def test_erro_de_rede_no_primeiro_o_segundo_responde(self):
        a, b = Falso(erro("falha de conexão com o provedor")), Falso(texto("resposta do segundo"))
        eventos, leitor = rodar({"deepseek:x": a, "claude-sonnet-5-5": b})
        self.assertEqual(tipos(eventos), ["fallback", "consulta", "texto", "fim"])
        self.assertEqual(eventos[0][1], {"de": "deepseek:x", "para": "claude-sonnet-5-5", "motivo": "falha de conexão com o provedor", "tentativa": 2})
        self.assertEqual(leitor.resposta, "resposta do segundo")
        self.assertEqual(leitor.modelo_pedido, "deepseek:x")
        self.assertEqual(leitor.modelo, "claude-sonnet-5-5")
        self.assertEqual(leitor.trocas, [eventos[0][1]])

    def test_leitor_e_zerado_entre_as_tentativas(self):
        a = Falso([("consulta", {"nome": "buscar"}), erro("429")[0]])
        b = Falso(texto("certo"))
        eventos, leitor = rodar({"a": a, "b": b})
        self.assertEqual(leitor.consultas, ["buscar"])      # só a do substituto, não duas
        self.assertEqual(leitor.resposta, "certo")

    def test_resposta_vazia_tambem_troca(self):
        a, b = Falso([("fim", {"duracao_ms": 1})]), Falso(texto("ok"))
        eventos, leitor = rodar({"a": a, "b": b})
        self.assertEqual(eventos[0][0], "fallback")
        self.assertEqual(eventos[0][1]["motivo"], "resposta vazia")
        self.assertEqual(leitor.resposta, "ok")

    def test_os_erros_de_provedor_que_o_site_e_o_whatsapp_veem_trocam(self):
        for motivo in ("chave recusada pelo provedor", "limite de uso do provedor atingido", "provedor com problema",
                       "A consulta demorou mais que o esperado.", "modelo x indisponível: chave não configurada (X_API_KEY)"):
            eventos, _ = rodar({"a": Falso(erro(motivo)), "b": Falso(texto("ok"))})
            self.assertEqual(tipos(eventos)[0], "fallback", motivo)

    def test_oserror_levantado_pelo_cliente_conta_como_falha_de_provedor(self):
        eventos, leitor = rodar({"a": Falso([ConnectionResetError("reset")]), "b": Falso(texto("ok"))})
        self.assertEqual(tipos(eventos)[0], "fallback")
        self.assertIn("ConnectionResetError", eventos[0][1]["motivo"])

    def test_prova_repetida_pelo_substituto_nao_aparece_duas_vezes(self):
        fonte = ("fonte", {"evidencia": "e1", "trecho": "t"})
        a, b = Falso([fonte, erro("429")[0]]), Falso([fonte, *texto("ok")])
        eventos, _ = rodar({"a": a, "b": b})
        self.assertEqual(tipos(eventos).count("fonte"), 1)

    def test_todos_falharam_o_erro_diz_quem_foi_tentado(self):
        eventos, leitor = rodar({"a": Falso(erro("429")), "b": Falso(erro("provedor com problema")), "c": Falso(erro("timeout"))})
        self.assertEqual(eventos[-1][1], {"motivo": "timeout", "nenhum_respondeu": True, "tentados": ["a", "b", "c"]})
        self.assertEqual(leitor.tentados, ["a", "b", "c"])      # cada um uma vez, nunca repetido

    def test_um_modelo_so_que_falha_nao_diz_nenhum_respondeu(self):
        eventos, _ = rodar({"a": Falso(erro("429"))})
        self.assertEqual(eventos, [("erro", {"motivo": "429"})])

    def test_ultimo_da_cadeia_falha_termina_em_erro(self):
        eventos, _ = rodar({"a": Falso(erro("429")), "b": Falso(erro("provedor com problema"))})
        self.assertEqual(tipos(eventos), ["fallback", "erro"])
        self.assertEqual(eventos[-1][1]["motivo"], "provedor com problema")


class TestTravas(unittest.TestCase):
    def test_depois_de_falar_nao_troca(self):
        a = Falso([("texto", {"delta": "Começo da resposta"}), erro("conexão caiu")[0]])
        b = Falso(texto("outra resposta"))
        eventos, leitor = rodar({"a": a, "b": b})
        self.assertEqual(tipos(eventos), ["texto", "erro"])
        self.assertEqual(b.chamado, 0)
        self.assertEqual(leitor.trocas, [])
        self.assertEqual(leitor.resposta, "Começo da resposta")

    def test_perfil_inexistente_levanta_antes_de_qualquer_provedor_e_nao_troca(self):
        a, b = Falso(texto("x")), Falso(texto("y"))
        with mock.patch.object(provedores, "escolher", side_effect=lambda m: {"a": a, "b": b}[m]), \
                mock.patch.object(provedores, "cadeia", return_value=["a", "b"]):
            with self.assertRaises(ValueError):
                list(agente.perguntar("pergunta", ["pe-inexistente"], modelo="a"))
        self.assertEqual((a.chamado, b.chamado), (0, 0))

    def test_valueerror_dentro_do_cliente_nao_vira_troca(self):
        a, b = Falso([ValueError("pergunta inválida")]), Falso(texto("y"))
        with self.assertRaises(ValueError):
            rodar({"a": a, "b": b})
        self.assertEqual(b.chamado, 0)

    def test_sem_fallback_nenhuma_troca_e_o_orcamento_inteiro(self):
        a, b = Falso(erro("429")), Falso(texto("y"))
        leitor = agente.Leitor()
        with mock.patch.object(provedores, "escolher", side_effect=lambda m: {"a": a, "b": b}[m]), \
                mock.patch.object(provedores, "cadeia", return_value=["a", "b"]) as cadeia:
            eventos = list(agente.perguntar("pergunta", TENANTS, leitor=leitor, modelo="a", permitir_fallback=False))
        cadeia.assert_not_called()
        self.assertEqual(eventos, [("erro", {"motivo": "429"})])
        self.assertEqual((a.chamado, b.chamado), (1, 0))
        self.assertAlmostEqual(a.limites[0], agente.LIMITE_S, delta=1)
        self.assertEqual((leitor.modelo, leitor.trocas), ("a", []))

    def test_fallback_ligado_com_um_modelo_so_mantem_o_orcamento_inteiro(self):
        a = Falso(texto("ok"))
        rodar({"a": a})
        self.assertAlmostEqual(a.limites[0], agente.LIMITE_S, delta=1)


class TestOrcamento(unittest.TestCase):
    def rodar_com_relogio(self, clientes, relogio, limite_s=110, primeira=35):
        with mock.patch.object(agente, "_agora", side_effect=lambda: relogio[0]), \
                mock.patch.object(agente, "LIMITE_S", limite_s), mock.patch.object(agente, "LIMITE_PRIMEIRA", primeira):
            return rodar(clientes)

    def test_tentativa_com_substituto_tem_teto_e_a_ultima_recebe_o_que_sobrou(self):
        r = [0.0]
        a, b, c = Falso([35, *erro("timeout")], r), Falso([30, *erro("429")], r), Falso(texto("ok"), r)
        eventos, leitor = self.rodar_com_relogio({"a": a, "b": b, "c": c}, r)
        self.assertEqual(a.limites, [35])
        self.assertEqual(b.limites, [35])       # min(35, 110 - 35 = 75)
        self.assertEqual(c.limites, [45])       # 110 - 35 - 30: o que sobrou
        self.assertEqual(tipos(eventos), ["fallback", "fallback", "consulta", "texto", "fim"])
        self.assertLessEqual(35 + 30 + c.limites[0], 110)

    def test_o_substituto_recebe_so_o_tempo_restante(self):
        r = [0.0]
        a, b = Falso([35, *erro("A consulta demorou mais que o esperado.")], r), Falso(texto("ok"), r)
        eventos, _ = self.rodar_com_relogio({"a": a, "b": b}, r, limite_s=50)
        self.assertEqual(a.limites, [35])
        self.assertEqual(b.limites, [15])       # 50 - 35

    def test_soma_das_tentativas_nunca_passa_do_limite(self):
        r = [0.0]
        a, b = Falso([35, *erro("timeout")], r), Falso([40, *erro("timeout")], r)
        eventos, _ = self.rodar_com_relogio({"a": a, "b": b}, r, limite_s=60)
        self.assertLessEqual(sum(c.limites[0] for c in (a, b)), 60)
        self.assertEqual(a.limites[0] + b.limites[0], 60)

    def test_sem_tempo_para_outra_tentativa_termina_com_erro_de_tempo(self):
        r = [0.0]
        a, b = Falso([58, *erro("timeout")], r), Falso(texto("ok"), r)     # estoura o teto e deixa 2 s
        eventos, _ = self.rodar_com_relogio({"a": a, "b": b}, r, limite_s=60)
        self.assertEqual(tipos(eventos), ["erro"])
        self.assertIn("demorou", eventos[0][1]["motivo"])
        self.assertEqual(b.chamado, 0)


class TestWorker(unittest.TestCase):
    """O evento novo não pode chegar à API do site (ela recusa tipo desconhecido) e o log tem que provar a troca."""

    def test_fallback_vai_para_o_log_e_nao_para_a_api(self):
        with mock.patch.dict(os.environ, {"WORKER_KEY": "k" * 30}):
            worker = importlib.import_module("worker")
        enviados, logs = [], []
        a, b = Falso(erro("limite de uso do provedor atingido")), Falso(texto("resposta"))
        pergunta = {"id": 7, "usuario_id": 1, "texto": "oi", "tenants": TENANTS}
        with mock.patch.object(provedores, "escolher", side_effect=lambda m: {"a": a, "b": b}[m]), \
                mock.patch.object(provedores, "cadeia", return_value=["a", "b"]), \
                mock.patch.object(agente, "MODELO", "a"), \
                mock.patch.object(worker, "api", side_effect=lambda met, rota, corpo=None: (enviados.extend((corpo or {}).get("eventos", [])), (200, None))[1]), \
                mock.patch.object(worker, "gravar_log", side_effect=lambda **c: logs.append(c)):
            worker.atender_site(pergunta)
        self.assertNotIn("fallback", [e["tipo"] for e in enviados])
        self.assertEqual([e["tipo"] for e in enviados if e["tipo"] in ("texto", "fim", "erro")], ["texto", "fim"])
        self.assertEqual(len(logs), 1)
        self.assertEqual((logs[0]["modelo_pedido"], logs[0]["modelo"], logs[0]["desfecho"]), ("a", "b", "concluida"))
        self.assertEqual(logs[0]["trocas"], [{"de": "a", "para": "b", "motivo": "limite de uso do provedor atingido", "tentativa": 2}])
        self.assertNotIn("chave-de-teste", json.dumps(logs, ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()
