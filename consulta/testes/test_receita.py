"""Cadastro de CNPJ da Receita (BrasilAPI): coleta e extração. Sem rede e sem Neo4j.

    python -m unittest discover -s consulta/testes -v
"""
import collections
import io
import json
import os
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

RAIZ = Path(__file__).resolve().parents[2]
os.environ.setdefault("BRUTO", str(RAIZ / "fixtures" / "exemplo" / "bruto"))
os.environ.setdefault("CHAVE_PF", "chave-de-teste")
sys.path.insert(0, str(RAIZ / "coleta"))
import extrair  # noqa: E402
import receita  # noqa: E402

PJ = "11222333000181"          # CNPJ válido
PJ2 = "11444777000161"         # CNPJ válido
CPF = "52998224725"            # CPF válido


def resposta_da_api(cnpj=PJ, **mudancas) -> dict:
    """Do jeito que a BrasilAPI devolve, com os campos que NÃO podemos guardar (sócios, contato, endereço)."""
    base = {"cnpj": cnpj, "razao_social": "EMPRESA EXEMPLO LTDA", "nome_fantasia": "EXEMPLO", "descricao_situacao_cadastral": "ATIVA",
            "data_situacao_cadastral": "2010-02-01", "descricao_motivo_situacao_cadastral": "SEM MOTIVO", "data_inicio_atividade": "2010-02-01",
            "cnae_fiscal": 4744099, "cnae_fiscal_descricao": "Comércio varejista de materiais de construção em geral",
            "natureza_juridica": "Sociedade Empresária Limitada", "porte": "DEMAIS", "descricao_identificador_matriz_filial": "MATRIZ",
            "municipio": "GARANHUNS", "uf": "PE", "capital_social": 500000, "opcao_pelo_simples": None, "opcao_pelo_mei": None,
            "qsa": [{"nome_socio": "FULANO DE TAL", "cnpj_cpf_do_socio": "***486734**"}], "email": "contato@exemplo.invalid",
            "ddd_telefone_1": "8730000000", "logradouro": "RUA EXEMPLO", "numero": "10", "bairro": "CENTRO", "cep": "55290000",
            "cnaes_secundarios": [{"codigo": 1, "descricao": "x"}]}
    return {**base, **mudancas}


class FalsaResposta(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def api_que_responde(por_cnpj: dict):
    """urlopen falso: devolve a resposta do CNPJ que está na URL, 404 se não houver, ou levanta o erro dado."""
    chamadas = []

    def urlopen(pedido, timeout=0):
        cnpj = pedido.full_url.rsplit("/", 1)[-1]
        chamadas.append(cnpj)
        valor = por_cnpj.get(cnpj, 404)
        if isinstance(valor, int):
            raise urllib.error.HTTPError(pedido.full_url, valor, "erro", {}, io.BytesIO(b""))
        return FalsaResposta(json.dumps(valor).encode("utf-8"))
    return urlopen, chamadas


class TestCnpj(unittest.TestCase):
    def test_digito_verificador(self):
        self.assertTrue(receita.cnpj_valido(PJ))
        for ruim in ("11222333000182", "00000000000000", "123", "", "1122233300018a"):
            self.assertFalse(receita.cnpj_valido(ruim), ruim)

    def test_so_digitos(self):
        self.assertEqual(receita.so_digitos("11.222.333/0001-81"), PJ)
        self.assertEqual(receita.so_digitos(None), "")


class TestReduzir(unittest.TestCase):
    def test_guarda_so_os_campos_da_lista_e_nunca_socios_contato_ou_endereco(self):
        r = receita.reduzir(resposta_da_api(), PJ)
        self.assertEqual(set(r), set(receita.CAMPOS))
        texto = json.dumps(r, ensure_ascii=False)
        for proibido in ("FULANO", "contato@", "8730000000", "RUA EXEMPLO", "55290000", "CENTRO", "qsa", "email"):
            self.assertNotIn(proibido, texto)

    def test_recusa_resposta_de_outro_cnpj_ou_que_nao_e_um_objeto(self):
        with self.assertRaises(ValueError):
            receita.reduzir(resposta_da_api(cnpj=PJ2), PJ)
        for estranho in (None, [], "texto", {"razao_social": "sem cnpj"}):
            with self.assertRaises(ValueError):
                receita.reduzir(estranho, PJ)


class TestColeta(unittest.TestCase):
    def setUp(self):
        self.pasta = tempfile.TemporaryDirectory()
        self.addCleanup(self.pasta.cleanup)
        self.bruto = Path(self.pasta.name)
        for patcher in (mock.patch.dict(os.environ, {"BRUTO": self.pasta.name}), mock.patch.object(receita, "INTERVALO_S", 0)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def rodar(self, argv, por_cnpj):
        urlopen, chamadas = api_que_responde(por_cnpj)
        with mock.patch.object(receita.urllib.request, "urlopen", urlopen), mock.patch("sys.stdout", io.StringIO()) as saida, \
                mock.patch("sys.stderr", io.StringIO()) as erro:
            codigo = receita.main(argv)
        return codigo, chamadas, saida.getvalue(), erro.getvalue()

    def test_grava_o_arquivo_com_fonte_url_data_e_so_os_campos_permitidos(self):
        codigo, chamadas, saida, _ = self.rodar(["11.222.333/0001-81"], {PJ: resposta_da_api()})
        self.assertEqual((codigo, chamadas), (0, [PJ]))
        self.assertIn("EMPRESA EXEMPLO LTDA | ATIVA", saida)
        doc = json.loads((self.bruto / f"receita-{PJ}.json").read_text(encoding="utf-8"))
        self.assertEqual(set(doc), {"fonte", "url", "coletado_em", "resposta"})
        self.assertTrue(doc["url"].endswith(f"/cnpj/v1/{PJ}"))
        self.assertEqual(set(doc["resposta"]), set(receita.CAMPOS))
        self.assertNotIn("FULANO", (self.bruto / f"receita-{PJ}.json").read_text(encoding="utf-8"))

    def test_cnpj_invalido_nao_gasta_pedido_e_o_codigo_de_saida_avisa(self):
        codigo, chamadas, _, erro = self.rodar(["11222333000182", PJ], {PJ: resposta_da_api()})
        self.assertEqual((codigo, chamadas), (1, [PJ]))
        self.assertIn("inválido", erro)

    def test_repetido_e_pedido_uma_vez_so(self):
        _, chamadas, _, _ = self.rodar([PJ, "11.222.333/0001-81", PJ], {PJ: resposta_da_api()})
        self.assertEqual(chamadas, [PJ])

    def test_404_nao_e_erro_e_a_lista_continua(self):
        codigo, chamadas, saida, _ = self.rodar([PJ2, PJ], {PJ: resposta_da_api()})
        self.assertEqual((codigo, chamadas), (0, [PJ2, PJ]))
        self.assertIn("não consta no cadastro", saida)
        self.assertFalse((self.bruto / f"receita-{PJ2}.json").exists())

    def test_limite_ou_recusa_para_sem_insistir(self):
        for codigo_http in (429, 403, 500):
            for f in self.bruto.glob("receita-*"):
                f.unlink()
            codigo, chamadas, _, erro = self.rodar([PJ2, PJ], {PJ2: codigo_http, PJ: resposta_da_api()})
            self.assertEqual((codigo, chamadas), (1, [PJ2]), codigo_http)           # o segundo nem foi pedido
            self.assertIn(str(codigo_http), erro)
            self.assertEqual(list(self.bruto.glob("receita-*")), [])

    def test_resposta_de_outro_cnpj_para_sem_gravar(self):
        codigo, _, _, erro = self.rodar([PJ], {PJ: resposta_da_api(cnpj=PJ2)})
        self.assertEqual(codigo, 1)
        self.assertIn("não é do CNPJ", erro)
        self.assertEqual(list(self.bruto.glob("receita-*")), [])

    def test_aceita_lista_em_arquivo_e_sem_argumento_avisa(self):
        lista = self.bruto / "lista.txt"
        lista.write_text(f"{PJ}\n{PJ2}\n", encoding="utf-8")
        _, chamadas, _, _ = self.rodar(["--arquivo", str(lista)], {PJ: resposta_da_api(), PJ2: resposta_da_api(PJ2)})
        self.assertEqual(chamadas, [PJ, PJ2])
        self.assertEqual(self.rodar([], {})[0], 1)


def pasta_com(**cadastros) -> tempfile.TemporaryDirectory:
    pasta = tempfile.TemporaryDirectory()
    for cnpj, resposta in cadastros.items():
        c = cnpj.removeprefix("c")
        (Path(pasta.name) / f"receita-{c}.json").write_text(json.dumps(
            {"fonte": receita.FONTE, "url": f"https://brasilapi.com.br/api/cnpj/v1/{c}", "coletado_em": "2026-11-14", "resposta": receita.reduzir(resposta, c)},
            ensure_ascii=False), encoding="utf-8")
    return pasta


def extrair_de(pasta: Path, **extra):
    saida = {k: [] for k in ("contratos", "processos", "fornecedores", "sancoes", "cadastros", "execucoes", "evidencias")}
    relatorio = collections.defaultdict(int)
    extrair.extrair_cadastros_receita(saida, relatorio, bruto=pasta)
    return saida, relatorio


class TestExtracao(unittest.TestCase):
    def test_cadastro_fornecedor_e_evidencia_com_o_hash_do_arquivo(self):
        pasta = pasta_com(**{f"c{PJ}": resposta_da_api()})
        self.addCleanup(pasta.cleanup)
        saida, rel = extrair_de(Path(pasta.name))
        (c,), (f,), (e,) = saida["cadastros"], saida["fornecedores"], saida["evidencias"]
        self.assertEqual((c["id"], c["fornecedor"], c["tenant"], c["sensibilidade"]), (f"receita:{PJ}", f"cnpj:{PJ}", "br-uniao", "publico"))
        self.assertEqual((c["razao_social"], c["situacao"], c["situacao_desde"], c["inicio_atividade"]), ("EMPRESA EXEMPLO LTDA", "ATIVA", "2010-02-01", "2010-02-01"))
        self.assertEqual((c["cnae"], c["porte"], c["matriz_filial"], c["municipio"], c["uf"], c["capital_social"]),
                         ("4744099", "DEMAIS", "MATRIZ", "GARANHUNS", "PE", 500000.0))
        self.assertEqual((f["id"], f["cnpj"], f["tipo"], f["nome"], f["tenant"], f["evidencia"]), (f"cnpj:{PJ}", PJ, "PJ", "EMPRESA EXEMPLO LTDA", "br-uniao", e["id"]))
        self.assertEqual(c["evidencia"], e["id"])
        self.assertEqual((c["nome_fantasia"], f["nome_fantasia"]), ("EXEMPLO", "EXEMPLO"))      # a marca entra no índice de busca
        self.assertEqual((e["arquivo"], e["tabela"], e["linha"], e["capturado_em"], e["tenant"]), (f"receita-{PJ}.json", "cadastro", 1, "2026-11-14", "br-uniao"))
        self.assertEqual(e["documento_hash"], extrair.sha256(Path(pasta.name) / f"receita-{PJ}.json"))
        self.assertIn(f"CNPJ {PJ}", e["trecho"])
        self.assertIn("situação ATIVA desde 01/02/2010", e["trecho"])
        self.assertIn("Receita Federal, via BrasilAPI", e["trecho"])
        self.assertEqual(rel["receita_cadastros"], 1)

    def test_nada_de_socio_contato_ou_endereco_chega_ao_resultado(self):
        pasta = pasta_com(**{f"c{PJ}": resposta_da_api()})
        self.addCleanup(pasta.cleanup)
        texto = json.dumps(extrair_de(Path(pasta.name))[0], ensure_ascii=False)
        for proibido in ("FULANO", "contato@", "8730000000", "RUA EXEMPLO", "55290000"):
            self.assertNotIn(proibido, texto)

    def test_cpf_colado_na_razao_social_de_mei_e_mascarado(self):
        pasta = pasta_com(**{f"c{PJ}": resposta_da_api(razao_social=f"JOSE EXEMPLO {CPF}", nome_fantasia=None)})
        self.addCleanup(pasta.cleanup)
        saida, _ = extrair_de(Path(pasta.name))
        self.assertNotIn(CPF, json.dumps(saida, ensure_ascii=False))
        self.assertEqual(saida["cadastros"][0]["razao_social"], "JOSE EXEMPLO [CPF]")

    def test_campos_vazios_viram_nulos_e_data_estranha_nao_quebra(self):
        pasta = pasta_com(**{f"c{PJ}": resposta_da_api(nome_fantasia="", data_situacao_cadastral="ontem", capital_social="abc", cnae_fiscal=None)})
        self.addCleanup(pasta.cleanup)
        (c,) = extrair_de(Path(pasta.name))[0]["cadastros"]
        self.assertEqual((c["nome_fantasia"], c["situacao_desde"], c["capital_social"], c["cnae"]), (None, None, None, None))

    def test_arquivo_estranho_e_contado_e_ignorado(self):
        pasta = pasta_com(**{f"c{PJ}": resposta_da_api()})
        self.addCleanup(pasta.cleanup)
        d = Path(pasta.name)
        (d / "receita-quebrado.json").write_text("{nao e json", encoding="utf-8")
        (d / f"receita-{PJ2}.json").write_text(json.dumps({"resposta": {"cnpj": PJ, "razao_social": "NOME NO ARQUIVO DE OUTRO CNPJ"}}), encoding="utf-8")   # nome do arquivo não bate
        (d / "receita-12345678000100.json").write_text(json.dumps({"resposta": {"cnpj": "12345678000100", "razao_social": "CNPJ INVALIDO"}}), encoding="utf-8")
        (d / "receita-sem-resposta.json").write_text(json.dumps({"fonte": "x"}), encoding="utf-8")
        saida, rel = extrair_de(d)
        self.assertEqual([c["id"] for c in saida["cadastros"]], [f"receita:{PJ}"])
        self.assertEqual((rel["receita_cadastros"], rel["receita_arquivo_invalido"]), (1, 4))

    def test_sem_arquivos_nao_faz_nada(self):
        pasta = tempfile.TemporaryDirectory()
        self.addCleanup(pasta.cleanup)
        saida, rel = extrair_de(Path(pasta.name))
        self.assertEqual((saida["cadastros"], dict(rel)), ([], {}))


if __name__ == "__main__":
    unittest.main()
