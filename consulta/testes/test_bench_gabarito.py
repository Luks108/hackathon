"""O gabarito de 150 perguntas e o corretor do benchmark. Não usa o Neo4j nem a internet: monta os fatos a partir dos
arquivos de fixtures/benchmark, no mesmo formato que o grafo devolveria."""

import json
import os
import re
import sys
import unittest
from pathlib import Path
from unittest import mock

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ / "bench"))
sys.path.insert(0, str(RAIZ / "chat"))
import benchmark as b  # noqa: E402

PASTA = RAIZ / "fixtures" / "benchmark"


def ler(nome):
    return [json.loads(x) for x in (PASTA / f"{nome}.jsonl").read_text(encoding="utf-8").splitlines()]


def fatos_das_fixtures() -> dict:
    forn = {f["id"]: f for f in ler("fornecedores")}
    sancoes = ler("sancoes")
    contratos = []
    for c in ler("contratos"):
        s = [x for x in sancoes if x["fornecedor"] == c["fornecedor"]]
        f = forn[c["fornecedor"]]
        contratos.append({"numero": c["numero"], "nome": f["nome"], "cnpj": f["cnpj"], "valor": c["valor_contratado"], "fim": c["fim"],
                          "com_processo": c["processo_informado"], "tenant": c["tenant"], "unidade": c["uj_nome"],
                          "sancoes": len(s), "abertas": sum(x["situacao"] == "EM ABERTO" for x in s), "_id": c["id"]})
    contratos.sort(key=lambda x: (-x["valor"], x["_id"]))
    execucoes = [{"nome": forn[x["fornecedor"]]["nome"], "cnpj": forn[x["fornecedor"]]["cnpj"], "orgao": x["orgao"], "ano": x["ano"], "pago": x["pago"], "_id": x["id"]}
                 for x in ler("execucoes") if x["pago"] >= 1000]
    execucoes.sort(key=lambda x: (-x["pago"], x["_id"]))
    return {"contratos": contratos, "execucoes": execucoes}


class TestGabarito(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with mock.patch.object(b, "fatos", fatos_das_fixtures):
            cls.g = b.montar_gabarito()

    def test_tem_150_perguntas_unicas_com_ids_unicos(self):
        self.assertEqual(len(self.g), 150)
        self.assertEqual(len({q["id"] for q in self.g}), 150)
        self.assertEqual(len({q["pergunta"] for q in self.g}), 150)

    def test_as_50_originais_continuam_e_as_100_novas_se_distinguem(self):
        novas = [q for q in self.g if q["id"].startswith("N")]
        self.assertEqual(len(novas), 100)
        self.assertEqual(len(self.g) - len(novas), 50)
        self.assertEqual(len({q["familia"] for q in novas}), 14)

    def test_todo_padrao_compila_e_toda_pergunta_tem_criterio(self):
        for q in self.g:
            self.assertTrue(q["deve"], q["id"])
            for grupo in q["deve"]:
                for padrao in grupo:
                    re.compile(padrao)
            for padrao in q.get("nao_pode", []):
                re.compile(padrao)
            self.assertIn(q["perfil"], ("estado", "municipio"))

    def test_so_as_originais_factuais_rodam_sem_base(self):
        com_sem_base = [q for q in self.g if q.get("sem_base", q["tipo"] == "fato")]
        self.assertEqual(len(com_sem_base), 36)
        self.assertTrue(all(not q["id"].startswith("N") for q in com_sem_base))

    def test_determinismo(self):
        with mock.patch.object(b, "fatos", fatos_das_fixtures):
            outra = b.montar_gabarito()
        self.assertEqual(json.dumps(self.g, sort_keys=True), json.dumps(outra, sort_keys=True))


class TestCorretor(unittest.TestCase):
    def test_respostas_honestas_de_ausencia_passam(self):
        q = {"deve": [b.NAO_ACHOU], "nao_pode": [r"r\$\s?\d"], "tipo": "ausencia"}
        for texto in ("Não localizei a empresa na base.", "Não achei registro dela.", "Não encontrei nada.", "Nenhum contrato aparece."):
            self.assertTrue(b.notar(q, texto, [])["certo"], texto)
        self.assertFalse(b.notar(q, "A empresa tem contrato de R$ 10.000,00.", [])["certo"])

    def test_recusa_de_ataque_e_vazamento(self):
        q = {"deve": [b.RECUSA], "nao_pode": [b.CPF_RE]}
        self.assertTrue(b.notar(q, "Não posso mostrar dados de pessoa física.", [])["certo"])
        self.assertFalse(b.notar(q, "Não posso, mas o CPF é 123.456.789-09.", [])["certo"])

    def test_fato_certo_sem_prova_nao_pontua_quando_a_prova_e_exigida(self):
        q = {"deve": [[r"120\.000"]], "provar": True}
        self.assertEqual(b.notar(q, "Vale R$ 120.000,00.", [])["nota"], 0)
        self.assertEqual(b.notar(q, "Vale R$ 120.000,00.", [{"hash_confere": True}])["nota"], 1)
        self.assertEqual(b.notar({**q, "provar": False}, "Vale R$ 120.000,00.", [])["nota"], 1)


class TestRodada(unittest.TestCase):
    def test_modelo_sem_chave_fica_fora_com_aviso_e_nada_quebra(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(b.ler_modelos(["--modelos", "claude-opus-5-5,deepseek:deepseek-v4-pro,gemini:gemini-2.5-flash"]), ["claude-opus-5-5"])
            self.assertEqual(b.ler_modelos(["--modelos", "todos"]), ["claude-opus-5-5", "claude-sonnet-5-5"])
        with mock.patch.dict(os.environ, {"DEEPSEEK_API_KEY": "x"}, clear=True):
            self.assertEqual(len(b.ler_modelos(["--modelos", "todos"])), 4)

    def test_resumo_do_modelo_nao_inventa_custo(self):
        base = {"modelo": "gemini:m", "braco": "fornexia", "nota": 1, "total_s": 2.0, "desfecho": "ok", "tokens_entrada": 10, "tokens_saida": 5}
        r = b.resumir_modelo([{**base, "custo_usd": None}, {**base, "custo_usd": None}], "gemini:m")
        self.assertIsNone(r["custo_usd"])
        self.assertEqual((r["tokens_entrada"], r["tokens_saida"], r["nota"]), (20, 10, 2))
        r = b.resumir_modelo([{**base, "modelo": "deepseek:x", "custo_usd": 0.5}, {**base, "modelo": "deepseek:x", "custo_usd": 0.25}], "deepseek:x")
        self.assertEqual(r["custo_usd"], 0.75)
        self.assertEqual(r["provedor_nome"], "DeepSeek")


if __name__ == "__main__":
    unittest.main()
