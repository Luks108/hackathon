"""A base fictícia do benchmark precisa ser coerente: sem isso o gabarito e o painel de teste não valem.
Não usa o Neo4j: lê os arquivos de fixtures/benchmark e confere o hash do arquivo bruto."""

import hashlib
import json
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
PASTA = RAIZ / "fixtures" / "benchmark"
BRUTO = RAIZ / "fixtures" / "exemplo" / "bruto" / "benchmark.html"


def ler(nome):
    return [json.loads(x) for x in (PASTA / f"{nome}.jsonl").read_text(encoding="utf-8").splitlines()]


class TestFixturesBenchmark(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contratos, cls.evidencias, cls.sancoes = ler("contratos"), ler("evidencias"), ler("sancoes")
        cls.execucoes, cls.fornecedores, cls.processos = ler("execucoes"), ler("fornecedores"), ler("processos")

    def test_tamanho_que_o_gabarito_exige(self):
        self.assertEqual(len(self.contratos), 120)
        self.assertEqual(sum(c["tenant"] == "pe-estado" for c in self.contratos), 84)
        self.assertEqual(sum(c["tenant"] == "pe-garanhuns" for c in self.contratos), 36)

    def test_valores_nao_empatam(self):
        valores = [c["valor_contratado"] for c in self.contratos]
        self.assertEqual(len(set(valores)), len(valores))

    def test_numeros_de_contrato_unicos(self):
        numeros = [c["numero"] for c in self.contratos]
        self.assertEqual(len(set(numeros)), len(numeros))

    def test_toda_evidencia_aponta_para_linha_do_arquivo_bruto_com_hash_certo(self):
        h = hashlib.sha256(BRUTO.read_bytes()).hexdigest()
        linhas = BRUTO.read_text(encoding="utf-8").count("<tr>")
        for e in self.evidencias:
            self.assertEqual(e["documento_hash"], h)
            self.assertLessEqual(e["linha"], linhas)
        self.assertEqual(len(self.evidencias), linhas)

    def test_todo_fato_tem_evidencia_existente(self):
        ids = {e["id"] for e in self.evidencias}
        for conjunto in (self.contratos, self.sancoes, self.execucoes, self.processos):
            for item in conjunto:
                self.assertIn(item["evidencia"], ids)

    def test_ha_fornecedores_nos_dois_entes_e_sancionados(self):
        por_ente = {t: {c["fornecedor"] for c in self.contratos if c["tenant"] == t} for t in ("pe-estado", "pe-garanhuns")}
        self.assertGreaterEqual(len(por_ente["pe-estado"] & por_ente["pe-garanhuns"]), 6)
        self.assertGreaterEqual(len({s["fornecedor"] for s in self.sancoes}), 16)
        self.assertTrue(all(s["tenant"] == "pe-estado" for s in self.sancoes))   # é o que dá sentido às perguntas de isolamento

    def test_tudo_e_marcado_como_ficticio_e_sem_pessoa_fisica(self):
        for e in self.evidencias:
            self.assertTrue(e["trecho"].startswith("DADO FICTÍCIO"))
        for f in self.fornecedores:
            self.assertEqual(f["tipo"], "PJ")
            self.assertIn("(fictícia)", f["nome"])
        for c in self.contratos:
            self.assertEqual(c["sensibilidade"], "publico")


if __name__ == "__main__":
    unittest.main()
