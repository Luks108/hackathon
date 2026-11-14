"""Contratos federais por CNPJ (Portal da Transparência) e contratos de órgão no PNCP: coleta e extração. Sem rede e sem Neo4j.

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
from datetime import date
from pathlib import Path
from unittest import mock

RAIZ = Path(__file__).resolve().parents[2]
os.environ.setdefault("BRUTO", str(RAIZ / "fixtures" / "exemplo" / "bruto"))
os.environ.setdefault("CHAVE_PF", "chave-de-teste")
sys.path.insert(0, str(RAIZ / "coleta"))
import extrair  # noqa: E402
import federal_contratos as fc  # noqa: E402
import pncp  # noqa: E402

PJ = "11222333000181"          # CNPJ válido
PJ2 = "11444777000161"         # CNPJ válido
CPF = "52998224725"            # CPF válido
ORGAO = "11303906000100"       # Prefeitura de Garanhuns (o único órgão do ORGAOS_PNCP)
CHAVE = "chave-secreta-de-teste-123"


class Resposta(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def http_erro(url, codigo):
    return urllib.error.HTTPError(url, codigo, "erro", {}, io.BytesIO(b""))


# ---------- contratos federais ----------

def contrato_federal(cnpj=PJ, id=1, **mudancas):
    base = {"id": id, "numero": "000062021", "objeto": "Objeto: PRESTAÇÃO DE SERVIÇOS TÉCNICOS DE EXEMPLO", "numeroProcesso": "10010.000001/2021-11",
            "fundamentoLegal": "Lei 8.666", "situacaoContrato": "Não se aplica", "modalidadeCompra": "Pregão",
            "compra": {"numero": "1", "contatoResponsavel": "FULANO DE TAL RESPONSAVEL"},
            "unidadeGestora": {"codigo": "170001", "nome": "SUPERINTENDENCIA REGIONAL EXEMPLO", "orgaoMaximo": {"codigo": "25000", "sigla": "MFAZ", "nome": "Ministério da Fazenda"}},
            "dataAssinatura": "2021-08-03", "dataPublicacaoDOU": "2021-08-05", "dataInicioVigencia": "2021-08-03", "dataFimVigencia": "2026-08-03",
            "fornecedor": {"id": 9, "cnpjFormatado": f"{cnpj[:2]}.{cnpj[2:5]}.{cnpj[5:8]}/{cnpj[8:12]}-{cnpj[12:]}", "razaoSocialReceita": "EMPRESA EXEMPLO LTDA", "nome": "EMPRESA EXEMPLO"},
            "valorInicialCompra": 110712.0, "valorFinalCompra": 127102.2}
    return {**base, **mudancas}


def api_federal(por_pagina: dict):
    """urlopen falso: devolve a lista da página pedida, ou levanta o erro dado. Guarda o que foi pedido."""
    pedidos = []

    def urlopen(pedido, timeout=0):
        pedidos.append(pedido)
        pagina = int(pedido.full_url.split("pagina=")[1].split("&")[0])
        valor = por_pagina.get(pagina, [])
        if isinstance(valor, int):
            raise http_erro(pedido.full_url, valor)
        return Resposta(json.dumps(valor).encode("utf-8"))
    return urlopen, pedidos


class TestColetaFederal(unittest.TestCase):
    def setUp(self):
        self.pasta = tempfile.TemporaryDirectory()
        self.addCleanup(self.pasta.cleanup)
        self.bruto = Path(self.pasta.name)
        for patcher in (mock.patch.dict(os.environ, {"BRUTO": self.pasta.name, "PORTAL_TRANSPARENCIA_CHAVE": CHAVE}), mock.patch.object(fc, "INTERVALO_S", 0)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def rodar(self, argv, por_pagina):
        urlopen, pedidos = api_federal(por_pagina)
        with mock.patch.object(fc.urllib.request, "urlopen", urlopen), mock.patch("sys.stdout", io.StringIO()) as saida, mock.patch("sys.stderr", io.StringIO()) as erro:
            codigo = fc.main(argv)
        return codigo, pedidos, saida.getvalue(), erro.getvalue()

    def test_pagina_ate_acabar_e_manda_a_chave_no_cabecalho(self):
        codigo, pedidos, saida, erro = self.rodar([PJ], {1: [contrato_federal(id=1)], 2: [contrato_federal(id=2)], 3: []})
        self.assertEqual(codigo, 0)
        self.assertEqual(len(pedidos), 3)
        self.assertTrue(all(p.get_header("Chave-api-dados") == CHAVE for p in pedidos))
        self.assertIn(f"cpfCnpj={PJ}", pedidos[0].full_url)
        self.assertNotIn(CHAVE, saida + erro + (self.bruto / f"federal-contratos-{PJ}.json").read_text(encoding="utf-8"))         # a chave não vai para a tela nem para o arquivo
        doc = json.loads((self.bruto / f"federal-contratos-{PJ}.json").read_text(encoding="utf-8"))
        self.assertEqual((len(doc["contratos"]), doc["completo"]), (2, True))

    def test_guarda_so_os_campos_permitidos_e_nunca_o_contato_do_responsavel(self):
        self.rodar([PJ], {1: [contrato_federal()]})
        texto = (self.bruto / f"federal-contratos-{PJ}.json").read_text(encoding="utf-8")
        self.assertNotIn("FULANO", texto)
        self.assertNotIn("contatoResponsavel", texto)
        c = json.loads(texto)["contratos"][0]
        self.assertEqual((c["numero"], c["valorInicialCompra"], c["unidadeGestora"]["orgaoMaximo"]["sigla"], c["fornecedor"]["cnpj"]), ("000062021", 110712.0, "MFAZ", PJ))

    def test_contrato_de_outro_fornecedor_para_sem_gravar(self):
        codigo, _, _, erro = self.rodar([PJ], {1: [contrato_federal(cnpj=PJ2)]})
        self.assertEqual(codigo, 1)
        self.assertIn("outro fornecedor", erro)
        self.assertEqual(list(self.bruto.glob("federal-contratos-*")), [])

    def test_limite_chave_recusada_ou_erro_para_sem_insistir(self):
        for http in (401, 429, 500):
            codigo, pedidos, _, erro = self.rodar([PJ, PJ2], {1: http})
            self.assertEqual((codigo, len(pedidos)), (1, 1), http)             # o segundo CNPJ nem foi pedido
            self.assertIn(str(http), erro)
        self.assertIn("chave recusada", self.rodar([PJ], {1: 401})[3])

    def test_cnpj_invalido_nao_gasta_pedido_e_cpf_nao_e_consultado(self):
        codigo, pedidos, _, erro = self.rodar(["11222333000182", CPF, PJ], {1: []})
        self.assertEqual((codigo, len(pedidos)), (1, 1))
        self.assertIn("inválido", erro)

    def test_sem_chave_para_antes_de_qualquer_pedido(self):
        with mock.patch.dict(os.environ, {"PORTAL_TRANSPARENCIA_CHAVE": ""}):
            with self.assertRaises(SystemExit):
                self.rodar([PJ], {})

    def test_fornecedor_com_mais_de_20_paginas_fica_marcado_como_incompleto(self):
        codigo, pedidos, saida, _ = self.rodar([PJ], {p: [contrato_federal(id=p)] for p in range(1, 40)})
        self.assertEqual((codigo, len(pedidos)), (0, fc.MAX_PAGINAS))
        self.assertFalse(json.loads((self.bruto / f"federal-contratos-{PJ}.json").read_text(encoding="utf-8"))["completo"])
        self.assertIn("incompleto", saida)

    def test_resposta_que_nao_e_lista_para(self):
        urlopen = lambda pedido, timeout=0: Resposta(b'{"erro": "x"}')  # noqa: E731
        with mock.patch.object(fc.urllib.request, "urlopen", urlopen), mock.patch("sys.stderr", io.StringIO()) as erro:
            self.assertEqual(fc.main([PJ]), 1)
        self.assertIn("inesperada", erro.getvalue())


def pasta_federal(cnpj=PJ, contratos=None, **doc) -> tempfile.TemporaryDirectory:
    pasta = tempfile.TemporaryDirectory()
    lista = contratos if contratos is not None else [fc.reduzir(contrato_federal(cnpj=cnpj), cnpj)]
    conteudo = {"fonte": fc.FONTE, "url": f"{fc.URL}?cpfCnpj={cnpj}", "coletado_em": "2026-11-14", "completo": True, "contratos": lista, **doc}
    (Path(pasta.name) / f"federal-contratos-{cnpj}.json").write_text(json.dumps(conteudo, ensure_ascii=False), encoding="utf-8")
    return pasta


def extrair_com(funcao, pasta: Path, **extra):
    saida = {k: [] for k in ("contratos", "processos", "fornecedores", "sancoes", "cadastros", "execucoes", "evidencias")}
    relatorio, sensiveis = collections.defaultdict(int), set()
    if funcao is extrair.extrair_contratos_pncp:
        funcao(saida, relatorio, bruto=pasta, sensiveis=sensiveis)
    else:
        funcao(saida, relatorio, bruto=pasta)
    return saida, relatorio, sensiveis


class TestExtracaoFederal(unittest.TestCase):
    def test_contrato_fornecedor_e_evidencia_com_o_hash_do_arquivo(self):
        pasta = pasta_federal()
        self.addCleanup(pasta.cleanup)
        saida, rel, _ = extrair_com(extrair.extrair_contratos_federais, Path(pasta.name))
        (c,), (f,), (e,) = saida["contratos"], saida["fornecedores"], saida["evidencias"]
        self.assertEqual((c["id"], c["tenant"], c["sensibilidade"], c["fornecedor"], c["evidencia"]), ("br-uniao:contrato:1", "br-uniao", "publico", f"cnpj:{PJ}", e["id"]))
        self.assertEqual((c["numero"], c["valor_contratado"], c["valor_final"], c["inicio"], c["fim"], c["orgao_superior"], c["situacao"]),
                         ("000062021", 110712.0, 127102.2, "2021-08-03", "2026-08-03", "MFAZ", "Não se aplica"))
        self.assertEqual((c["tem_aditivo"], c["processo_informado"], c["processo"]), (None, True, None))      # a API não diz se há aditivo: nada de inferir
        self.assertEqual((c["uj"], c["uj_nome"]), ("br-uniao:uj:170001", "SUPERINTENDENCIA REGIONAL EXEMPLO"))
        self.assertEqual((f["id"], f["nome"], f["tenant"]), (f"cnpj:{PJ}", "EMPRESA EXEMPLO LTDA", "br-uniao"))
        self.assertEqual(c["objeto"], "PRESTAÇÃO DE SERVIÇOS TÉCNICOS DE EXEMPLO")                      # sem o prefixo "Objeto:" do portal
        self.assertEqual((e["tabela"], e["linha"], e["capturado_em"], e["tenant"]), ("contratos", 1, "2026-11-14", "br-uniao"))
        self.assertEqual(e["documento_hash"], extrair.sha256(Path(pasta.name) / f"federal-contratos-{PJ}.json"))
        for esperado in ("contrato 000062021", "R$ 110.712,00", "R$ 127.102,20", "MFAZ", f"CNPJ {PJ}"):
            self.assertIn(esperado, e["trecho"])
        self.assertEqual(rel["federal_contratos"], 1)

    def test_unidade_invalida_do_portal_vira_unidade_nao_informada(self):
        ruim = fc.reduzir(contrato_federal(unidadeGestora={"codigo": "-1", "nome": "Inválido", "orgaoMaximo": {"sigla": "-1", "nome": "Inválido"}}), PJ)
        pasta = pasta_federal(contratos=[ruim])
        self.addCleanup(pasta.cleanup)
        (c,) = extrair_com(extrair.extrair_contratos_federais, Path(pasta.name))[0]["contratos"]
        self.assertEqual((c["uj_nome"], c["orgao_superior"]), ("Unidade não informada", None))

    def test_item_de_outro_cnpj_e_arquivo_estranho_sao_contados_e_ignorados(self):
        outro = fc.reduzir(contrato_federal(cnpj=PJ2, id=7), PJ2)
        pasta = pasta_federal(contratos=[fc.reduzir(contrato_federal(), PJ), outro])
        self.addCleanup(pasta.cleanup)
        d = Path(pasta.name)
        (d / "federal-contratos-12345678000100.json").write_text(json.dumps({"contratos": []}), encoding="utf-8")         # CNPJ inválido no nome
        (d / "federal-contratos-quebrado.json").write_text("{nao e json", encoding="utf-8")
        saida, rel, _ = extrair_com(extrair.extrair_contratos_federais, d)
        self.assertEqual([c["idc"] for c in saida["contratos"]], ["1"])
        self.assertEqual((rel["federal_contratos_item_invalido"], rel["federal_contratos_arquivo_invalido"]), (1, 2))

    def test_sem_arquivos_nao_faz_nada(self):
        pasta = tempfile.TemporaryDirectory()
        self.addCleanup(pasta.cleanup)
        saida, rel, _ = extrair_com(extrair.extrair_contratos_federais, Path(pasta.name))
        self.assertEqual((saida["contratos"], dict(rel)), ([], {}))


# ---------- PNCP ----------

def contrato_pncp(controle="11303906000100-2-000001/2026", ni=PJ, tipo="PJ", **mudancas):
    base = {"numeroControlePNCP": controle, "anoContrato": 2026, "sequencialContrato": 1, "numeroContratoEmpenho": "045/2026", "objetoContrato": "CONTRATACAO  DE EMPRESA\nESPECIALIZADA EXEMPLO",
            "valorInicial": 0.0, "valorGlobal": 620000.0, "valorAcumulado": 0.0, "dataAssinatura": "2026-01-20", "dataVigenciaInicio": "2026-01-20", "dataVigenciaFim": "2026-12-31",
            "dataPublicacaoPncp": "2026-01-22", "tipoPessoa": tipo, "niFornecedor": ni, "nomeRazaoSocialFornecedor": "EMPRESA EXEMPLO LTDA" if tipo == "PJ" else "MARIA DE EXEMPLO",
            "processo": "12/2026", "usuarioNome": "SERVIDOR QUE PUBLICOU", "informacaoComplementar": "texto livre com dados",
            "orgaoEntidade": {"cnpj": ORGAO, "razaoSocial": "MUNICIPIO DE GARANHUNS", "poderId": "E"},
            "unidadeOrgao": {"codigoUnidade": "1", "nomeUnidade": "SECRETARIA DE EXEMPLO", "municipioNome": "Garanhuns", "ufSigla": "PE", "ufNome": "Pernambuco"}}
    return {**base, **mudancas}


def api_pncp(paginas: dict):
    pedidos = []

    def urlopen(pedido, timeout=0):
        pedidos.append(pedido.full_url)
        pagina = int(pedido.full_url.split("pagina=")[1].split("&")[0])
        valor = paginas.get(pagina, {"data": [], "totalRegistros": 0, "totalPaginas": 0})
        if isinstance(valor, int):
            raise http_erro(pedido.full_url, valor)
        return Resposta(json.dumps(valor).encode("utf-8"))
    return urlopen, pedidos


class TestJanelas(unittest.TestCase):
    def test_ate_365_dias_cabe_numa_janela(self):
        self.assertEqual(pncp.janelas(date(2026, 1, 1), date(2026, 11, 14)), [(date(2026, 1, 1), date(2026, 11, 14))])
        self.assertEqual(len(pncp.janelas(date(2026, 1, 1), date(2026, 12, 31))), 1)

    def test_mais_que_isso_divide_sem_buraco_nem_sobreposicao(self):
        j = pncp.janelas(date(2024, 1, 1), date(2026, 11, 14))
        self.assertGreater(len(j), 1)
        self.assertEqual((j[0][0], j[-1][1]), (date(2024, 1, 1), date(2026, 11, 14)))
        for (_, fim), (ini, _) in zip(j, j[1:]):
            self.assertEqual((ini - fim).days, 1)
        self.assertTrue(all((b - a).days + 1 <= 365 for a, b in j))

    def test_data_final_antes_da_inicial_e_erro(self):
        with self.assertRaises(ValueError):
            pncp.janelas(date(2026, 2, 1), date(2026, 1, 1))


class TestColetaPncp(unittest.TestCase):
    def setUp(self):
        self.pasta = tempfile.TemporaryDirectory()
        self.addCleanup(self.pasta.cleanup)
        self.bruto = Path(self.pasta.name)
        for patcher in (mock.patch.dict(os.environ, {"BRUTO": self.pasta.name}), mock.patch.object(pncp, "INTERVALO_S", 0)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def rodar(self, argv, paginas):
        urlopen, pedidos = api_pncp(paginas)
        with mock.patch.object(pncp.urllib.request, "urlopen", urlopen), mock.patch("sys.stdout", io.StringIO()) as saida, mock.patch("sys.stderr", io.StringIO()) as erro:
            codigo = pncp.main(argv)
        return codigo, pedidos, saida.getvalue(), erro.getvalue()

    def test_pagina_de_10_ate_a_ultima_e_grava_so_os_campos_permitidos(self):
        paginas = {1: {"data": [contrato_pncp(f"c{i}") for i in range(10)], "totalRegistros": 12, "totalPaginas": 2},
                   2: {"data": [contrato_pncp("c10"), contrato_pncp("c11")], "totalRegistros": 12, "totalPaginas": 2}}
        codigo, pedidos, saida, _ = self.rodar([ORGAO, "--de", "2026-01-01", "--ate", "2026-11-14"], paginas)
        self.assertEqual((codigo, len(pedidos)), (0, 2))
        self.assertIn("tamanhoPagina=10", pedidos[0])
        self.assertIn(f"cnpjOrgao={ORGAO}", pedidos[0])
        self.assertIn("dataInicial=20260101", pedidos[0])
        arquivo = self.bruto / f"pncp-{ORGAO}-20260101-20261114.json"
        texto = arquivo.read_text(encoding="utf-8")
        for proibido in ("SERVIDOR QUE PUBLICOU", "texto livre", "usuarioNome"):
            self.assertNotIn(proibido, texto)
        doc = json.loads(texto)
        self.assertEqual((len(doc["contratos"]), doc["total"], doc["completo"]), (12, 12, True))
        self.assertIn("12 contratos", saida)

    def test_janela_maior_que_365_dias_vira_dois_pedidos(self):
        paginas = {1: {"data": [contrato_pncp("a")], "totalRegistros": 1, "totalPaginas": 1}}
        codigo, pedidos, _, _ = self.rodar([ORGAO, "--de", "2025-01-01", "--ate", "2026-06-30"], paginas)
        self.assertEqual((codigo, len(pedidos)), (0, 2))
        self.assertIn("dataInicial=20250101", pedidos[0])
        self.assertIn("dataFinal=20260630", pedidos[1])

    def test_erro_do_servidor_para_sem_insistir_e_sem_gravar(self):
        for http in (429, 500, 422):
            codigo, pedidos, _, erro = self.rodar([ORGAO, "--de", "2026-01-01", "--ate", "2026-02-01"], {1: http})
            self.assertEqual((codigo, len(pedidos)), (1, 1), http)
            self.assertIn("parando", erro)
        self.assertEqual(list(self.bruto.glob("pncp-*")), [])

    def test_contrato_de_outro_orgao_para(self):
        outro = contrato_pncp(orgaoEntidade={"cnpj": "00000000000191", "razaoSocial": "OUTRO"})
        codigo, _, _, erro = self.rodar([ORGAO, "--de", "2026-01-01", "--ate", "2026-02-01"], {1: {"data": [outro], "totalRegistros": 1, "totalPaginas": 1}})
        self.assertEqual(codigo, 1)
        self.assertIn("outro órgão", erro)

    def test_argumentos_errados_nao_chegam_a_rede(self):
        for argv in ([], ["--de", "2026-01-01"], [ORGAO], [ORGAO, "--de", "ontem"], ["123", "--de", "2026-01-01"]):
            codigo, pedidos, _, _ = self.rodar(argv, {})
            self.assertEqual((codigo, pedidos), (1, []), argv)

    def test_total_diferente_do_lido_marca_incompleto(self):
        paginas = {1: {"data": [contrato_pncp("a")], "totalRegistros": 5, "totalPaginas": 1}}
        _, _, saida, _ = self.rodar([ORGAO, "--de", "2026-01-01", "--ate", "2026-02-01"], paginas)
        self.assertIn("incompleto", saida)


def pasta_pncp(*arquivos: list) -> tempfile.TemporaryDirectory:
    pasta = tempfile.TemporaryDirectory()
    for i, contratos in enumerate(arquivos):
        reduzidos = [pncp.reduzir(c, ORGAO) if c["orgaoEntidade"]["cnpj"] == ORGAO else c for c in contratos]
        doc = {"fonte": pncp.FONTE, "url": f"{pncp.URL}?cnpjOrgao={ORGAO}", "coletado_em": "2026-11-14", "contratos": reduzidos}
        (Path(pasta.name) / f"pncp-{ORGAO}-2026010{i + 1}-20261114.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    return pasta


class TestExtracaoPncp(unittest.TestCase):
    def test_contrato_de_pj_no_ente_do_orgao_com_prova(self):
        pasta = pasta_pncp([contrato_pncp()])
        self.addCleanup(pasta.cleanup)
        saida, rel, _ = extrair_com(extrair.extrair_contratos_pncp, Path(pasta.name))
        (c,), (f,), (e,) = saida["contratos"], saida["fornecedores"], saida["evidencias"]
        self.assertEqual((c["id"], c["tenant"], c["sensibilidade"], c["fonte"], c["fornecedor"]), ("pe-garanhuns:pncp:11303906000100-2-000001/2026", "pe-garanhuns", "publico", "PNCP", f"cnpj:{PJ}"))
        self.assertEqual((c["numero"], c["valor_contratado"], c["inicio"], c["fim"], c["tem_aditivo"], c["processo_informado"]), ("045/2026", 620000.0, "2026-01-20", "2026-12-31", None, True))
        self.assertEqual(c["objeto"], "CONTRATACAO DE EMPRESA ESPECIALIZADA EXEMPLO")                # quebra de linha e espaço duplo viram um espaço
        self.assertEqual((c["uj"], c["uj_nome"]), ("pe-garanhuns:uj:pncp:1", "SECRETARIA DE EXEMPLO"))
        self.assertEqual((f["id"], f["tenant"], f["nome"]), (f"cnpj:{PJ}", "pe-garanhuns", "EMPRESA EXEMPLO LTDA"))
        self.assertEqual((e["tenant"], e["tabela"], e["capturado_em"]), ("pe-garanhuns", "contratos", "2026-11-14"))
        for esperado in ("Contrato no PNCP", "contrato 045/2026", "R$ 620.000,00", f"CNPJ {PJ}"):
            self.assertIn(esperado, e["trecho"])
        self.assertEqual(rel["pncp_contratos"], 1)

    def test_valor_zero_do_pncp_e_valor_nao_informado_e_nao_zero(self):
        pasta = pasta_pncp([contrato_pncp(valorGlobal=0.0, valorInicial=0.0), contrato_pncp("c2", valorGlobal=0.0, valorInicial=8000.0)])
        self.addCleanup(pasta.cleanup)
        saida, _, _ = extrair_com(extrair.extrair_contratos_pncp, Path(pasta.name))
        self.assertEqual([c["valor_contratado"] for c in saida["contratos"]], [None, 8000.0])
        self.assertIn("valor não informado", saida["evidencias"][0]["trecho"])

    def test_pessoa_fisica_so_como_hash_sem_nome_nem_documento(self):
        pasta = pasta_pncp([contrato_pncp(ni=CPF, tipo="PF")])
        self.addCleanup(pasta.cleanup)
        saida, rel, sensiveis = extrair_com(extrair.extrair_contratos_pncp, Path(pasta.name))
        (c,), (f,), (e,) = saida["contratos"], saida["fornecedores"], saida["evidencias"]
        self.assertEqual((c["sensibilidade"], c["fornecedor"]), ("pessoal", f"pf:{extrair.pseudonimo(CPF)}"))
        self.assertEqual((f["tipo"], f["cnpj"], f["nome"]), ("PF", None, None))
        self.assertTrue(e["trecho_mascarado"])
        texto = json.dumps(saida, ensure_ascii=False)
        for proibido in (CPF, "MARIA DE EXEMPLO"):
            self.assertNotIn(proibido, texto)
        self.assertIn(CPF, sensiveis)
        self.assertEqual(rel["pncp_contratos_pf"], 1)

    def test_o_mesmo_contrato_em_duas_janelas_vale_uma_vez(self):
        pasta = pasta_pncp([contrato_pncp("igual")], [contrato_pncp("igual"), contrato_pncp("outro")])
        self.addCleanup(pasta.cleanup)
        saida, rel, _ = extrair_com(extrair.extrair_contratos_pncp, Path(pasta.name))
        self.assertEqual(sorted(c["idc"] for c in saida["contratos"]), ["igual", "outro"])
        self.assertEqual(rel["pncp_repetido"], 1)

    def test_orgao_fora_do_mapa_documento_invalido_e_item_sem_controle_sao_contados(self):
        estranho = contrato_pncp("x", orgaoEntidade={"cnpj": "00000000000191", "razaoSocial": "OUTRO ORGAO"})
        pasta = pasta_pncp([estranho, contrato_pncp("y", ni="12345678000100"), contrato_pncp(None), contrato_pncp("z")])
        self.addCleanup(pasta.cleanup)
        (Path(pasta.name) / "pncp-quebrado.json").write_text("{nao e json", encoding="utf-8")
        saida, rel, _ = extrair_com(extrair.extrair_contratos_pncp, Path(pasta.name))
        self.assertEqual([c["idc"] for c in saida["contratos"]], ["z"])
        self.assertEqual((rel["pncp_orgao_sem_mapa"], rel["pncp_fornecedor_invalido"], rel["pncp_item_invalido"], rel["pncp_arquivo_invalido"]), (1, 1, 1, 1))

    def test_cpf_colado_no_nome_ou_no_objeto_e_mascarado(self):
        pasta = pasta_pncp([contrato_pncp(nomeRazaoSocialFornecedor=f"JOSE EXEMPLO {CPF}", objetoContrato=f"SERVICO PARA O CPF {CPF}")])
        self.addCleanup(pasta.cleanup)
        saida, _, _ = extrair_com(extrair.extrair_contratos_pncp, Path(pasta.name))
        self.assertNotIn(CPF, json.dumps(saida, ensure_ascii=False))

    def test_sem_arquivos_nao_faz_nada(self):
        pasta = tempfile.TemporaryDirectory()
        self.addCleanup(pasta.cleanup)
        saida, rel, _ = extrair_com(extrair.extrair_contratos_pncp, Path(pasta.name))
        self.assertEqual((saida["contratos"], dict(rel)), ([], {}))


if __name__ == "__main__":
    unittest.main()
