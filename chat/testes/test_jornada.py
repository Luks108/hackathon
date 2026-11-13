"""scripts/jornada.py: reconstruir a jornada de uma pergunta a partir dos logs por subsistema (só leitura).

    python -m unittest chat.testes.test_jornada -v
"""
import contextlib
import io
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ / "scripts"))
import jornada  # noqa: E402


def linha(ts, sub, evento, rid=None, nivel="info", **c):
    return json.dumps({"ts": f"2026-11-12T20:00:{ts}-03:00", "nivel": nivel, "subsistema": sub, "evento": evento,
                       **({"request_id": rid} if rid else {}), **c}, ensure_ascii=False)


class TestJornada(unittest.TestCase):
    def setUp(self):
        self.pasta = Path(tempfile.mkdtemp(prefix="jornada-"))
        w = lambda nome, *l: (self.pasta / nome).write_text("\n".join(l) + "\n", encoding="utf-8")  # noqa: E731
        w("gateway.jsonl", linha("01.100", "gateway", "recebida", "wa:A", tipo="texto"), linha("01.200", "gateway", "recebida", "wa:B", tipo="texto"),
          linha("09.500", "gateway", "envio", "wa:A", op="enviar", ok=True, duracao_ms=300))
        w("worker.jsonl", linha("01.300", "worker", "entrada_na_fila", "wa:A", espera_ms=800), linha("01.400", "worker", "inicio", "wa:A"),
          linha("09.000", "worker", "desfecho", "wa:A", respondeu=True, motivo=None, canal="whatsapp", duracao_ms=7600, modelo="claude-x"),
          linha("05.000", "worker", "desfecho", "wa:B", nivel="erro", respondeu=False, motivo="provedor", canal="whatsapp", duracao_ms=3000,
                modelo="claude-x", detalhe="modelo x: saldo insuficiente (HTTP 402)"))
        w("agente.jsonl", linha("02.000", "agente", "tentativa_fim", "wa:A", modelo="claude-x", tokens_entrada=100), "isto não é json")
        w("ferramentas.jsonl", linha("03.000", "ferramentas", "chamada", "wa:A", tool="cobertura", resultados=1, duracao_ms=40))
        w("seguranca.jsonl", linha("01.350", "seguranca", "entrada_suspeita", "wa:A", nivel="aviso", regra="ignorar_regras", trecho="ignore as regras"))
        w("saude.jsonl", linha("20.000", "saude", "componente_caiu", None, nivel="aviso", componente="gateway"))
        w("agente.jsonl.1", linha("00.500", "agente", "inicio", "wa:A"))          # cópia girada: também entra

    def tearDown(self):
        shutil.rmtree(self.pasta, ignore_errors=True)

    def rodar(self, *args):
        saida = io.StringIO()
        with contextlib.redirect_stdout(saida):
            codigo = jornada.main([*args, "--pasta", str(self.pasta)])
        return codigo, saida.getvalue()

    def test_a_jornada_de_uma_pergunta_junta_todos_os_arquivos_em_ordem_de_horario(self):
        codigo, texto = self.rodar("wa:A")
        self.assertEqual(codigo, 0)
        eventos = [l.split()[3] for l in texto.splitlines()]
        self.assertEqual(eventos, ["inicio", "recebida", "entrada_na_fila", "entrada_suspeita", "inicio", "tentativa_fim", "chamada", "desfecho", "envio"])
        self.assertNotIn("wa:B", texto)
        self.assertIn("ignorar_regras", texto)

    def test_id_que_nao_existe_diz_isso_e_aponta_o_caminho(self):
        _, texto = self.rodar("wa:NAO")
        self.assertIn("Nenhuma linha", texto)
        self.assertIn("--ultimas", texto)

    def test_ultimas_mostra_o_desfecho_de_cada_pergunta(self):
        _, texto = self.rodar("--ultimas")
        self.assertIn("wa:A", texto)
        self.assertIn("wa:B", texto)
        self.assertIn("provedor", texto)

    def test_falhas_traz_so_as_nao_respondidas_com_detalhe_e_contagem_por_motivo(self):
        _, texto = self.rodar("--falhas")
        self.assertIn("wa:B", texto)
        self.assertNotIn("wa:A ", texto)
        self.assertIn("HTTP 402", texto)
        self.assertIn("provedor=1", texto)

    def test_seguranca_e_saude(self):
        self.assertIn("ignorar_regras", self.rodar("--seguranca")[1])
        self.assertIn("componente_caiu", self.rodar("--saude")[1])

    def test_so_le_e_pasta_vazia_avisa(self):
        antes = sorted(p.name for p in self.pasta.iterdir())
        self.rodar("wa:A")
        self.assertEqual(sorted(p.name for p in self.pasta.iterdir()), antes)
        vazia = Path(tempfile.mkdtemp(prefix="jornada-vazia-"))
        try:
            saida = io.StringIO()
            with contextlib.redirect_stdout(saida):
                self.assertEqual(jornada.main(["--ultimas", "--pasta", str(vazia)]), 1)
            self.assertIn("Nenhum log", saida.getvalue())
        finally:
            shutil.rmtree(vazia, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
