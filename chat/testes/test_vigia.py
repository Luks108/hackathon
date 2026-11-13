"""Vigia de saúde (chat/vigia.py): quando cada peça cai, quando passa de 2 minutos fora e quando volta, com a duração.
O relógio é simulado: nenhum teste espera de verdade.

    python -m unittest chat.testes.test_vigia -v
"""
import json
import os
import shutil
import socket
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import vigia  # noqa: E402


class Relogio:
    def __init__(self, t=1_760_000_000.0):
        self.t = t

    def __call__(self):
        return self.t

    def avanca(self, s):
        self.t += s


class Base(unittest.TestCase):
    def setUp(self):
        self.pasta = Path(tempfile.mkdtemp(prefix="vigia-"))
        self.env = mock.patch.dict(os.environ, {"FORNEXIA_LOGS_DIR": str(self.pasta)})
        self.env.start()
        os.environ.pop("LOG_NIVEL", None)
        self.relogio = Relogio()

    def tearDown(self):
        self.env.stop()
        shutil.rmtree(self.pasta, ignore_errors=True)

    def saude(self):
        arq = self.pasta / "saude.jsonl"
        return [json.loads(l) for l in arq.read_text(encoding="utf-8").splitlines()] if arq.exists() else []

    def eventos(self):
        return [(l["evento"], l.get("componente")) for l in self.saude() if l["evento"].startswith("componente_")]


class TestQuedaEVolta(Base):
    def novo(self, estado, limite_s=120):
        """Vigia com um único componente, cujo estado (True = bem) o teste controla."""
        return vigia.Vigia({"gateway": lambda: (estado["bem"], "" if estado["bem"] else estado.get("motivo", "sem sinal"))},
                           limite_s=limite_s, relogio=self.relogio)

    def test_tudo_bem_nao_escreve_nada(self):
        v = self.novo({"bem": True})
        for _ in range(5):
            v.passo()
            self.relogio.avanca(15)
        self.assertEqual(self.eventos(), [])

    def test_queda_longa_escreve_caiu_depois_alem_do_limite_uma_vez_e_voltou_com_a_duracao(self):
        est = {"bem": True}
        v = self.novo(est)
        v.passo()
        est.update(bem=False, motivo="sem sinal há 95 s")
        self.relogio.avanca(15)
        inicio_queda = self.relogio.t
        v.passo()                                           # t+0: caiu
        self.assertEqual(self.eventos(), [("componente_caiu", "gateway")])
        for _ in range(7):                                  # +105 s: ainda dentro do limite de 120 s
            self.relogio.avanca(15)
            v.passo()
        self.assertEqual(self.eventos(), [("componente_caiu", "gateway")])
        self.relogio.avanca(15)                             # +120 s: passou do limite
        v.passo()
        for _ in range(10):                                 # e continua fora: o alerta NÃO se repete
            self.relogio.avanca(15)
            v.passo()
        self.assertEqual([e for e, _ in self.eventos()].count("componente_fora_alem_do_limite"), 1)
        est["bem"] = True
        self.relogio.avanca(15)
        v.passo()
        caiu, fora, voltou = [l for l in self.saude() if l["evento"].startswith("componente_")][0], \
            [l for l in self.saude() if l["evento"] == "componente_fora_alem_do_limite"][0], \
            [l for l in self.saude() if l["evento"] == "componente_voltou"][0]
        self.assertEqual((caiu["nivel"], fora["nivel"], voltou["nivel"]), ("aviso", "erro", "info"))
        self.assertEqual(fora["limite_s"], 120)
        self.assertGreaterEqual(fora["fora_ha_s"], 120)
        self.assertEqual(datetime.fromisoformat(voltou["inicio_queda"]).timestamp(), inicio_queda)       # hora de início
        self.assertEqual(datetime.fromisoformat(voltou["fim_queda"]).timestamp(), self.relogio.t)        # hora de fim
        self.assertEqual(voltou["duracao_s"], round(self.relogio.t - inicio_queda, 1))
        self.assertTrue(voltou["passou_do_limite"])
        self.assertEqual(voltou["motivo_da_queda"], "sem sinal há 95 s")

    def test_a_queda_conta_do_ultimo_sinal_de_vida_e_nao_de_quando_o_vigia_notou(self):
        """O worker morreu há 50 s (último batimento) e o vigia só notou agora: faltam 70 s, não 120, para passar de 2 minutos."""
        ultimo = self.relogio.t - 50
        v = vigia.Vigia({"worker": lambda: (False, "sem batimento há 50 s", ultimo)}, limite_s=120, relogio=self.relogio)
        v.passo()
        caiu = [l for l in self.saude() if l["evento"] == "componente_caiu"][0]
        self.assertEqual(datetime.fromisoformat(caiu["desde"]).timestamp(), ultimo)
        self.assertEqual(datetime.fromisoformat(caiu["detectado_em"]).timestamp(), self.relogio.t)
        self.relogio.avanca(69)
        v.passo()
        self.assertNotIn("componente_fora_alem_do_limite", [e for e, _ in self.eventos()])
        self.relogio.avanca(2)                      # 121 s desde o último batimento
        v.passo()
        fora = [l for l in self.saude() if l["evento"] == "componente_fora_alem_do_limite"][0]
        self.assertGreaterEqual(fora["fora_ha_s"], 120)

    def test_queda_curta_so_escreve_caiu_e_voltou_sem_alerta_de_limite(self):
        est = {"bem": False}
        v = self.novo(est)
        v.passo()
        self.relogio.avanca(30)
        est["bem"] = True
        v.passo()
        self.assertEqual(self.eventos(), [("componente_caiu", "gateway"), ("componente_voltou", "gateway")])
        voltou = [l for l in self.saude() if l["evento"] == "componente_voltou"][0]
        self.assertEqual((voltou["duracao_s"], voltou["passou_do_limite"]), (30.0, False))

    def test_cada_componente_tem_o_proprio_estado(self):
        est = {"worker": True, "gateway": True}
        v = vigia.Vigia({n: (lambda n=n: (est[n], "" if est[n] else "fora")) for n in est}, limite_s=120, relogio=self.relogio)
        est["worker"] = False
        v.passo()
        self.assertEqual(self.eventos(), [("componente_caiu", "worker")])

    def test_limite_configuravel(self):
        est = {"bem": False}
        v = self.novo(est, limite_s=30)
        v.passo()
        self.relogio.avanca(31)
        v.passo()
        self.assertIn(("componente_fora_alem_do_limite", "gateway"), self.eventos())

    def test_checagem_que_levanta_conta_como_queda_e_nao_derruba_as_outras(self):
        def quebrada():
            raise RuntimeError("boom")
        v = vigia.Vigia({"a": quebrada, "b": lambda: (False, "fora")}, limite_s=120, relogio=self.relogio)
        v.passo()
        self.assertEqual(sorted(self.eventos()), [("componente_caiu", "a"), ("componente_caiu", "b")])
        self.assertIn("RuntimeError", [l for l in self.saude() if l.get("componente") == "a"][0]["motivo"])

    def test_se_o_vigia_reinicia_no_meio_da_queda_ela_continua_contando_do_inicio_certo(self):
        est = {"bem": False}
        v1 = self.novo(est)
        v1.passo()
        inicio = self.relogio.t
        self.relogio.avanca(60)
        v2 = self.novo(est)                  # reinício: lê logs/saude-estado.json
        v2.iniciar()
        v2.passo()
        self.assertEqual([e for e, _ in self.eventos()], ["componente_caiu"])      # não escreve "caiu" de novo
        self.relogio.avanca(70)              # 130 s desde o início real da queda
        v2.passo()
        self.assertIn("componente_fora_alem_do_limite", [e for e, _ in self.eventos()])
        est["bem"] = True
        v2.passo()
        voltou = [l for l in self.saude() if l["evento"] == "componente_voltou"][0]
        self.assertEqual(datetime.fromisoformat(voltou["inicio_queda"]).timestamp(), inicio)

    def test_vigia_que_ficou_parado_registra_o_intervalo_cego(self):
        v1 = self.novo({"bem": True})
        v1.passo()
        self.relogio.avanca(600)
        v2 = self.novo({"bem": True})
        v2.iniciar()
        cego = [l for l in self.saude() if l["evento"] == "vigia_ficou_cego"]
        self.assertEqual(len(cego), 1)
        self.assertEqual((cego[0]["nivel"], cego[0]["duracao_s"]), ("aviso", 600.0))
        self.assertEqual([l["evento"] for l in self.saude()].count("vigia_iniciou"), 1)


class TestChecagens(Base):
    def escrever(self, caminho: Path, **dados):
        caminho.parent.mkdir(parents=True, exist_ok=True)
        caminho.write_text(json.dumps(dados), encoding="utf-8")

    def test_worker_depende_do_batimento(self):
        arq = self.pasta / "saude-worker.json"
        self.assertFalse(vigia.checar_worker(self.relogio, self.pasta)[0])             # sem arquivo
        self.escrever(arq, ts_epoch=self.relogio.t - 10, parando=False)
        self.assertEqual(vigia.checar_worker(self.relogio, self.pasta), (True, ""))
        self.escrever(arq, ts_epoch=self.relogio.t - 60, parando=False)
        bem, motivo, desde = vigia.checar_worker(self.relogio, self.pasta)
        self.assertFalse(bem)
        self.assertIn("60", motivo)
        self.assertEqual(desde, self.relogio.t - 60)          # a queda conta do último batimento, não de quando o vigia notou
        self.escrever(arq, ts_epoch=self.relogio.t, parando=True)
        self.assertEqual(vigia.checar_worker(self.relogio, self.pasta), (False, "parado de forma limpa", self.relogio.t))

    def test_gateway_depende_do_status_json(self):
        arq = self.pasta / "status.json"
        iso = lambda s: datetime.fromtimestamp(self.relogio.t - s).astimezone().isoformat()  # noqa: E731
        self.assertFalse(vigia.checar_gateway(self.relogio, self.pasta)[0])
        self.escrever(arq, conectado=True, atualizado=iso(20))
        self.assertEqual(vigia.checar_gateway(self.relogio, self.pasta), (True, ""))
        self.escrever(arq, conectado=False, atualizado=iso(20))
        self.assertIn("sem conexão", vigia.checar_gateway(self.relogio, self.pasta)[1])
        self.escrever(arq, conectado=True, atualizado=iso(200))
        self.assertIn("sem sinal", vigia.checar_gateway(self.relogio, self.pasta)[1])
        self.escrever(arq, conectado=False, atualizado=iso(5), parado=True)
        self.assertEqual(vigia.checar_gateway(self.relogio, self.pasta)[:2], (False, "parado de forma limpa"))
        self.escrever(arq, conectado=True)
        self.assertIn("sem horário", vigia.checar_gateway(self.relogio, self.pasta)[1])

    def test_neo4j_e_site_contra_porta_aberta_e_fechada(self):
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            s.listen(1)
            porta = s.getsockname()[1]
            self.assertEqual(vigia.checar_neo4j(f"bolt://127.0.0.1:{porta}"), (True, ""))
        bem, motivo = vigia.checar_neo4j(f"bolt://127.0.0.1:{porta}")         # agora fechada
        self.assertFalse(bem)
        self.assertIn("sem conexão", motivo)
        self.assertFalse(vigia.checar_site(f"http://127.0.0.1:{porta}", timeout=1)[0])

    def test_nome_de_componente_desconhecido_e_recusado(self):
        with self.assertRaises(SystemExit):
            vigia.montar_checagens(["gateway", "banana"])


if __name__ == "__main__":
    unittest.main()
