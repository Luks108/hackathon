"""O caminho de uma mensagem do WhatsApp dentro do worker, de ponta a ponta, SEM WhatsApp e SEM gastar token.

O gateway de mentira é o arquivo `inbound.jsonl` (o que o gateway real grava) e a pasta `outbox/` (o que ele consome). O agente é
substituído por um gerador de eventos. Cobre: a ordem dos pedidos de saída (reação, "digitando", resposta), o perfil de quem escreve,
os tipos de mensagem, o cursor (linha incompleta, reinício, sessão de canal aberta), o log e o contrato com o gateway em TypeScript.

    python -m unittest discover -s chat/testes -v
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
with mock.patch.dict(os.environ, {"WORKER_KEY": "k" * 30}):
    import worker  # noqa: E402

RAIZ = worker.RAIZ
NUM_SITE = "5500999990001"        # números fictícios (DDD 00)
NUM_MANUAL = "5500999990002"
CPF = "123.456.789-09"


def msg(i: int, texto: str = "Existe sanção em aberto?", tipo: str = "texto", remetente: str = NUM_MANUAL, **extra) -> dict:
    return {"id": f"M{i}", "chat_id": f"{remetente}@s.whatsapp.net", "remetente": remetente, "nome": "Teste", "ts": 1760000000 + i,
            "texto": texto, "tipo": tipo, "grupo": False, **extra}


def agente_falso(texto="Há uma sanção em aberto.", fontes=(), erro=None, levanta=None):
    """Substituto de agente.perguntar. Guarda as chamadas em `.chamadas`."""
    chamadas = []

    def perguntar(pergunta, tenants, historico=None, leitor=None, **kw):
        chamadas.append({"pergunta": pergunta, "tenants": list(tenants), "historico": list(historico or [])})
        if levanta:
            raise levanta
        for f in fontes:
            yield ("fonte", f)
        if erro:
            yield ("erro", {"motivo": erro})
            return
        leitor.resposta += texto
        yield ("texto", {"delta": texto})
        yield ("fim", {"duracao_ms": 5})

    perguntar.chamadas = chamadas
    return perguntar


class Base(unittest.TestCase):
    def setUp(self):
        self.estado = Path(tempfile.mkdtemp(prefix="wa-fluxo-"))
        (self.estado / "outbox").mkdir()
        self.logs = []
        self.perfis = {normalizar(NUM_SITE): ["pe-garanhuns"]}
        worker.historicos.clear()
        self.patches = [
            mock.patch.object(worker, "ESTADO", self.estado),
            mock.patch.object(worker, "sessao_de_canal_aberta", return_value=False),
            mock.patch.object(worker, "perfis_por_numero", self.perfis),
            mock.patch.object(worker, "transcrever", return_value=None),
        ]
        self.p_log = mock.patch.object(worker, "gravar_log", side_effect=lambda **c: self.logs.append(c))
        self.patches.append(self.p_log)
        for p in self.patches:
            p.start()
        self.inbound = self.estado / "inbound.jsonl"
        self.marca = self.estado / "worker.cursor"

    def tearDown(self):
        for p in self.patches:
            p.stop()
        shutil.rmtree(self.estado, ignore_errors=True)

    def chegam(self, *mensagens: dict, completo=True):
        linhas = "".join(json.dumps(m, ensure_ascii=False) + "\n" for m in mensagens)
        if not completo:
            linhas = linhas.rstrip("\n")
        with self.inbound.open("a", encoding="utf-8") as f:
            f.write(linhas)

    def passo(self, cursor=0, agente=None) -> int:
        agente = agente or agente_falso()
        tamanho = lambda: self.inbound.stat().st_size if self.inbound.exists() else 0  # noqa: E731
        relogio = iter(1_760_000_000 + i * 0.002 for i in range(10_000))
        with mock.patch.object(worker.agente, "perguntar", agente), mock.patch.object(worker.time, "time", side_effect=lambda: next(relogio)):
            return worker._passo_whatsapp(self.inbound, self.marca, tamanho, cursor)

    def saida(self) -> list[dict]:
        """Pedidos que o gateway receberia, na ordem em que o gateway os drena (nome do arquivo)."""
        return [json.loads(p.read_text(encoding="utf-8")) for p in sorted((self.estado / "outbox").glob("*.json"))]


def normalizar(n):
    return worker.normalizar(n)


class TestUmaMensagemDeTexto(Base):
    def test_ordem_da_saida_reacao_digitando_e_resposta(self):
        self.chegam(msg(1))
        self.passo()
        ops = [(p["op"], p["chat_id"]) for p in self.saida()]
        self.assertEqual([o for o, _ in ops], ["reagir", "digitando", "enviar"])
        self.assertEqual({c for _, c in ops}, {f"{NUM_MANUAL}@s.whatsapp.net"})
        reacao, digitando, resposta = self.saida()
        self.assertEqual((reacao["message_id"], reacao["emoji"]), ("M1", "👀"))
        self.assertTrue(digitando["ligado"])
        self.assertEqual(resposta["texto"], "Há uma sanção em aberto.")

    def test_resposta_leva_a_fonte_com_data_em_ordem_brasileira_e_o_link(self):
        fonte = {"trecho": "Sanção da empresa X | em aberto", "capturado_em": "2026-11-05", "url": "https://portal.exemplo/s"}
        self.chegam(msg(1))
        self.passo(agente=agente_falso(fontes=[fonte]))
        texto = self.saida()[-1]["texto"]
        self.assertIn("📎", texto)
        self.assertIn("Captura: 05/11/2026", texto)
        self.assertIn("https://portal.exemplo/s", texto)

    def test_so_as_3_primeiras_fontes_entram_na_resposta(self):
        fontes = [{"trecho": f"trecho {i}", "capturado_em": "2026-11-05", "url": None} for i in range(6)]
        self.chegam(msg(1))
        self.passo(agente=agente_falso(fontes=fontes))
        self.assertEqual(self.saida()[-1]["texto"].count("📎"), 3)

    def test_resposta_enorme_e_cortada_em_3800_caracteres(self):
        self.chegam(msg(1))
        self.passo(agente=agente_falso(texto="x" * 5000))
        self.assertEqual(len(self.saida()[-1]["texto"]), 3800)

    def test_pergunta_longa_e_cortada_em_500_caracteres(self):
        agente = agente_falso()
        self.chegam(msg(1, texto="a" * 900))
        self.passo(agente=agente)
        self.assertEqual(len(agente.chamadas[0]["pergunta"]), 500)

    def test_mensagem_so_com_espacos_nao_responde_nada(self):
        agente = agente_falso()
        self.chegam(msg(1, texto="   \n  "))
        self.passo(agente=agente)
        self.assertEqual(self.saida(), [])
        self.assertEqual(agente.chamadas, [])

    def test_segunda_pergunta_do_mesmo_chat_leva_o_historico(self):
        agente = agente_falso(texto="Resposta um.")
        self.chegam(msg(1, texto="Primeira?"), msg(2, texto="E a segunda?"))
        self.passo(agente=agente)
        self.assertEqual(agente.chamadas[0]["historico"], [])
        self.assertEqual(agente.chamadas[1]["historico"], [("Primeira?", "Resposta um.")])

    def test_historicos_de_chats_diferentes_nao_se_misturam(self):
        agente = agente_falso(texto="Resposta.")
        self.chegam(msg(1, remetente=NUM_MANUAL), msg(2, remetente=NUM_SITE))
        self.passo(agente=agente)
        self.assertEqual(agente.chamadas[1]["historico"], [])


class TestPerfil(Base):
    def test_numero_do_site_recebe_os_entes_do_plano_e_o_liberado_a_mao_o_perfil_manual(self):
        agente = agente_falso()
        self.chegam(msg(1, remetente=NUM_SITE), msg(2, remetente=NUM_MANUAL))
        self.passo(agente=agente)
        self.assertEqual(agente.chamadas[0]["tenants"], ["pe-garanhuns"])
        self.assertEqual(agente.chamadas[1]["tenants"], worker.PERFIL_MANUAL)

    def test_numero_com_e_sem_o_nono_digito_acha_o_mesmo_perfil(self):
        sem_nove = NUM_SITE[:4] + NUM_SITE[5:]
        agente = agente_falso()
        self.chegam(msg(1, remetente=sem_nove))
        self.passo(agente=agente)
        self.assertEqual(agente.chamadas[0]["tenants"], ["pe-garanhuns"])


class TestTiposDeMensagem(Base):
    def test_imagem_figurinha_e_outros_recebem_a_resposta_padrao_e_nao_chamam_o_agente(self):
        for tipo in ("imagem", "video", "documento", "figurinha", "outro"):
            agente = agente_falso()
            self.chegam(msg(1, texto="", tipo=tipo))
            self.passo(cursor=0, agente=agente)
            self.assertEqual(agente.chamadas, [], tipo)
            self.assertIn("texto ou áudio", self.saida()[-1]["texto"])
            shutil.rmtree(self.estado / "outbox"); (self.estado / "outbox").mkdir()
            self.inbound.unlink()

    def test_audio_transcrito_vira_a_pergunta(self):
        agente = agente_falso()
        with mock.patch.object(worker, "transcrever", return_value="existe sanção para a empresa tal"):
            self.chegam(msg(1, texto="", tipo="audio", arquivo=str(self.estado / "a.ogg")))
            self.passo(agente=agente)
        self.assertEqual(agente.chamadas[0]["pergunta"], "existe sanção para a empresa tal")
        self.assertEqual(self.saida()[-1]["op"], "enviar")

    def test_audio_sem_transcricao_pede_texto_e_nao_chama_o_agente(self):
        agente = agente_falso()
        self.chegam(msg(1, texto="", tipo="audio", arquivo=str(self.estado / "a.ogg")))     # transcrever devolve None (sem ffmpeg/whisper)
        self.passo(agente=agente)
        self.assertEqual(agente.chamadas, [])
        self.assertEqual([p["op"] for p in self.saida()], ["enviar"])
        self.assertIn("mandar por texto", self.saida()[0]["texto"])

    def test_audio_cuja_midia_nao_foi_baixada_recebe_a_resposta_padrao(self):
        self.chegam(msg(1, texto="", tipo="audio"))
        self.passo()
        self.assertIn("texto ou áudio", self.saida()[0]["texto"])


class TestFalhas(Base):
    def test_erro_do_agente_responde_a_mensagem_padrao_e_registra_erro(self):
        self.chegam(msg(1))
        self.passo(agente=agente_falso(erro="provedor com problema"))
        self.assertEqual(self.saida()[-1]["texto"], worker.ERRO_PADRAO)
        self.assertEqual(self.logs[-1]["desfecho"], "erro")

    def test_excecao_do_agente_responde_a_mensagem_padrao(self):
        self.chegam(msg(1))
        self.passo(agente=agente_falso(levanta=RuntimeError("boom")))
        self.assertEqual(self.saida()[-1]["texto"], worker.ERRO_PADRAO)

    def test_uma_mensagem_que_falha_nao_impede_a_seguinte(self):
        agente = agente_falso()
        self.chegam({"id": "ruim"}, msg(2))               # primeira linha sem os campos obrigatórios
        self.passo(agente=agente)
        self.assertEqual(len(agente.chamadas), 1)
        self.assertEqual(self.saida()[-1]["texto"], "Há uma sanção em aberto.")

    def test_linha_com_json_invalido_e_pulada(self):
        with self.inbound.open("a", encoding="utf-8") as f:
            f.write("isto não é json\n")
        self.chegam(msg(2))
        agente = agente_falso()
        self.passo(agente=agente)
        self.assertEqual(len(agente.chamadas), 1)

    def test_resposta_vazia_do_agente_vira_mensagem_padrao(self):
        self.chegam(msg(1))
        self.passo(agente=agente_falso(texto=""))
        self.assertEqual(self.saida()[-1]["texto"], worker.ERRO_PADRAO)

    def test_falha_nao_entra_no_historico(self):
        agente = agente_falso(erro="x")
        self.chegam(msg(1))
        self.passo(agente=agente)
        self.assertEqual(len(worker.historicos[f"wa:{NUM_MANUAL}@s.whatsapp.net"]), 0)


class TestCursor(Base):
    def test_linha_incompleta_nao_e_consumida_e_sai_quando_completa(self):
        agente = agente_falso()
        self.chegam(msg(1), completo=True)
        self.chegam(msg(2), completo=False)               # o gateway ainda está escrevendo a 2ª
        cursor = self.passo(agente=agente)
        self.assertEqual(len(agente.chamadas), 1)
        with self.inbound.open("a", encoding="utf-8") as f:
            f.write("\n")                                 # terminou de escrever
        cursor = self.passo(cursor=cursor, agente=agente)
        self.assertEqual(len(agente.chamadas), 2)
        self.assertEqual(int(self.marca.read_text()), cursor)

    def test_nada_e_atendido_duas_vezes(self):
        agente = agente_falso()
        self.chegam(msg(1))
        cursor = self.passo(agente=agente)
        self.passo(cursor=cursor, agente=agente)
        self.assertEqual(len(agente.chamadas), 1)

    def test_arquivo_que_encolheu_recomeca_do_zero(self):
        agente = agente_falso()
        self.chegam(msg(1))
        self.passo(cursor=10_000_000, agente=agente)      # cursor maior que o arquivo (arquivo trocado)
        self.assertEqual(len(agente.chamadas), 1)

    def test_sessao_de_canal_aberta_segura_as_mensagens_e_nao_as_perde(self):
        agente = agente_falso()
        self.chegam(msg(1))
        with mock.patch.object(worker, "sessao_de_canal_aberta", return_value=True):
            cursor = self.passo(agente=agente)
        self.assertEqual((cursor, agente.chamadas, self.saida()), (0, [], []))     # a sessão do claude é quem responde
        self.passo(cursor=cursor, agente=agente)                                   # fechou a sessão: o worker atende
        self.assertEqual(len(agente.chamadas), 1)

    def test_primeira_vez_ignora_o_historico_e_depois_continua_de_onde_parou(self):
        self.chegam(msg(1), msg(2))                       # chegaram com o worker desligado, antes de ele existir
        visto = []
        with mock.patch.object(worker, "_passo_whatsapp", side_effect=lambda a, m, t, c: (visto.append(c), worker.parar.set(), c)[2]):
            worker.parar.clear()
            worker.laco_whatsapp()
        self.assertEqual(visto, [self.inbound.stat().st_size])      # cursor começa no fim do arquivo
        worker.parar.clear()
        self.marca.write_text("7")
        visto.clear()
        with mock.patch.object(worker, "_passo_whatsapp", side_effect=lambda a, m, t, c: (visto.append(c), worker.parar.set(), c)[2]):
            worker.laco_whatsapp()
        worker.parar.clear()
        self.assertEqual(visto, [7])                      # com o cursor gravado, retoma dele


class TestLog(Base):
    def test_log_do_whatsapp_tem_canal_modelo_e_nao_guarda_cpf(self):
        self.chegam(msg(1, texto=f"Qual o contrato do titular {CPF}?"))
        self.passo()
        reg = self.logs[-1]
        self.assertEqual((reg["canal"], reg["desfecho"], reg["id"]), ("whatsapp", "concluida", "M1"))
        self.assertIn("modelo_pedido", reg)
        self.assertIn("trocas", reg)
        self.assertEqual(reg["tenants"], worker.PERFIL_MANUAL)

    def test_cpf_digitado_e_mascarado_pela_funcao_de_log_real(self):
        """Sem o gravar_log falso: o arquivo de log de verdade."""
        self.p_log.stop()
        self.patches.remove(self.p_log)
        with mock.patch.object(worker, "LOG", self.estado / "chat.jsonl"):
            self.chegam(msg(1, texto=f"Qual o contrato do titular {CPF}?"))
            self.passo()
        linha = (self.estado / "chat.jsonl").read_text(encoding="utf-8")
        self.assertNotIn(CPF, linha)
        self.assertIn("[CPF]", linha)


class TestContratoComOGateway(unittest.TestCase):
    """O worker e o gateway (TypeScript) só se falam por arquivos: o formato tem que ser o mesmo dos dois lados."""

    def test_toda_operacao_que_o_worker_pede_e_entendida_pelo_gateway(self):
        ts = (RAIZ / "canal-whatsapp" / "comum.ts").read_text(encoding="utf-8")
        gateway = (RAIZ / "canal-whatsapp" / "gateway.ts").read_text(encoding="utf-8")
        py = (RAIZ / "chat" / "worker.py").read_text(encoding="utf-8")
        do_worker = set(re.findall(r'"op": "(\w+)"', py))
        do_tipo = set(re.findall(r"op: '(\w+)'", ts))
        tratadas = set(re.findall(r"p\.op === '(\w+)'", gateway)) | {"enviar"}     # `enviar` é o caminho final de executar()
        self.assertEqual(do_worker, {"reagir", "digitando", "enviar"})
        self.assertTrue(do_worker <= do_tipo, f"o tipo Pedido não prevê {do_worker - do_tipo}")
        self.assertTrue(do_worker <= tratadas, f"o gateway não trata {do_worker - tratadas}")

    @unittest.skipUnless(shutil.which("bun") and (RAIZ / "canal-whatsapp" / "node_modules").is_dir(), "precisa do bun e de `bun install`")
    def test_pedido_do_worker_e_pedido_do_acesso_ts_tem_o_mesmo_formato(self):
        estado = Path(tempfile.mkdtemp(prefix="wa-contrato-"))
        try:
            (estado / "outbox").mkdir()
            with mock.patch.object(worker, "ESTADO", estado):
                worker.pedir({"op": "enviar", "chat_id": f"{NUM_MANUAL}@s.whatsapp.net", "texto": "oi"})
            do_worker = json.loads(next((estado / "outbox").glob("*.json")).read_text(encoding="utf-8"))
            r = subprocess.run([shutil.which("bun"), "acesso.ts", "teste", NUM_MANUAL, "oi"], cwd=RAIZ / "canal-whatsapp", capture_output=True, text=True,
                               env={**os.environ, "WHATSAPP_STATE_DIR": str(estado)}, timeout=60)
            self.assertEqual(r.returncode, 0, r.stderr)
            do_ts = [json.loads(p.read_text(encoding="utf-8")) for p in (estado / "outbox").glob("*.json") if p.read_text(encoding="utf-8") != json.dumps(do_worker, ensure_ascii=False)]
            self.assertEqual(set(do_worker), set(do_ts[0]))
            self.assertEqual((do_worker["op"], do_worker["chat_id"], do_worker["texto"]), (do_ts[0]["op"], do_ts[0]["chat_id"], do_ts[0]["texto"]))
        finally:
            shutil.rmtree(estado, ignore_errors=True)

    def test_o_que_o_gateway_grava_em_inbound_tem_os_campos_que_o_worker_le(self):
        ts = (RAIZ / "canal-whatsapp" / "comum.ts").read_text(encoding="utf-8")
        bloco = ts[ts.index("export interface Inbound"):ts.index("export type Pedido")]
        campos = set(re.findall(r"^\s+(\w+)\??:", bloco, re.M))
        for usado in ("id", "chat_id", "remetente", "tipo", "texto", "arquivo"):
            self.assertIn(usado, campos, f"o worker lê m['{usado}'], mas o gateway não o grava")


if __name__ == "__main__":
    unittest.main()
