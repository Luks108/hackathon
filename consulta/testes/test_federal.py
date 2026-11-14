"""CEIS e CNEP (sanções da União): coleta, extração e amostra. Sem rede e sem Neo4j.

    python -m unittest discover -s consulta/testes -v
"""
import collections
import contextlib
import io
import json
import os
import re
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
os.environ.setdefault("BRUTO", str(RAIZ / "fixtures" / "exemplo" / "bruto"))     # o extrair.py exige as duas variáveis ao ser importado
os.environ.setdefault("CHAVE_PF", "chave-de-teste")
sys.path.insert(0, str(RAIZ / "coleta"))
sys.path.insert(0, str(RAIZ / "consulta"))
import amostra  # noqa: E402
import extrair  # noqa: E402
import federal  # noqa: E402
import perfis  # noqa: E402

PJ = "11222333000181"          # CNPJ válido
PJ2 = "11444777000161"         # CNPJ válido
CPF = "52998224725"            # CPF válido
CAB_CEIS = ("CADASTRO;CÓDIGO DA SANÇÃO;TIPO DE PESSOA;CPF OU CNPJ DO SANCIONADO;NOME DO SANCIONADO;NOME INFORMADO PELO ÓRGÃO SANCIONADOR;"
            "RAZÃO SOCIAL - CADASTRO RECEITA;NOME FANTASIA - CADASTRO RECEITA;NÚMERO DO PROCESSO;CATEGORIA DA SANÇÃO;DATA INÍCIO SANÇÃO;"
            "DATA FINAL SANÇÃO;DATA PUBLICAÇÃO;PUBLICAÇÃO;DETALHAMENTO DO MEIO DE PUBLICAÇÃO;DATA DO TRÂNSITO EM JULGADO;ABRAGÊNCIA DA SANÇÃO;"
            "ÓRGÃO SANCIONADOR;UF ÓRGÃO SANCIONADOR;ESFERA ÓRGÃO SANCIONADOR;FUNDAMENTAÇÃO LEGAL;DATA ORIGEM INFORMAÇÃO;ORIGEM INFORMAÇÕES;OBSERVAÇÕES")
CAB_CNEP = CAB_CEIS.replace("CATEGORIA DA SANÇÃO;", "CATEGORIA DA SANÇÃO;VALOR DA MULTA;")


def linha(cadastro="CEIS", cod="1", doc=PJ, nome="Empresa Exemplo Ltda", receita="", processo="PAR 1/2020", categoria="Impedimento/proibição de contratar com prazo determinado",
          multa=None, inicio="22/11/2018", fim="22/11/2028", pub="05/11/2018", abrangencia="Sem Informação", orgao="Ministério Exemplo", fund="LEI 8666 ART 87"):
    campos = [cadastro, cod, "J" if len(doc) == 14 else "F", doc, nome, nome, receita, "", processo, categoria]
    if multa is not None:
        campos.append(multa)
    campos += [inicio, fim, pub, "DOU", "", "", abrangencia, orgao, "DF", "FEDERAL", fund, "", "", "texto livre do portal"]
    return ";".join(campos)


def cpf_com_zero_a_esquerda() -> str:
    base = "012345678"
    for n in (9, 10):
        resto = sum(int(a) * b for a, b in zip(base, range(n + 1, 1, -1))) * 10 % 11
        base += str(resto % 10)
    return base


def pasta_com(ceis=None, cnep=None, meta=True) -> Path:
    pasta = tempfile.TemporaryDirectory()
    caminho = Path(pasta.name)
    for cad, cab, linhas in (("ceis", CAB_CEIS, ceis), ("cnep", CAB_CNEP, cnep)):
        if linhas is None:
            continue
        (caminho / f"federal-{cad}.csv").write_bytes(("\r\n".join([cab, *linhas]) + "\r\n").encode("cp1252"))
        if meta:
            (caminho / f"federal-{cad}.meta.json").write_text(json.dumps(
                {"cadastro": cad.upper(), "data_do_arquivo": "2026-11-13", "coletado_em": "2026-11-14",
                 "url": f"https://portaldatransparencia.gov.br/download-de-dados/{cad}/20261113"}), encoding="utf-8")
    return pasta


def extrair_de(pasta: Path):
    saida = {k: [] for k in ("contratos", "processos", "fornecedores", "sancoes", "execucoes", "evidencias")}
    relatorio, sensiveis = collections.defaultdict(int), set()
    extrair.extrair_sancoes_federais(saida, relatorio, bruto=pasta, sensiveis=sensiveis)
    return saida, relatorio, sensiveis


class TestColeta(unittest.TestCase):
    PAGINA = ('<script>arquivos.push({"ano" : "2026", "mes" : "11", "dia" : "12", "origem" :  "CEIS"});\n'
              'arquivos.push({"ano" : "2026", "mes" : "11", "dia" : "13", "origem" :  "CEIS"});\n'
              'arquivos.push({"ano" : "2026", "mes" : "9", "dia" : "30", "origem" :  "CEIS"});\n'
              'arquivos.push({"ano" : "2026", "mes" : "11", "dia" : "14", "origem" :  "CNEP"});</script>')

    def test_escolhe_a_data_mais_recente_do_cadastro_pedido(self):
        self.assertEqual(federal.data_mais_recente(self.PAGINA, "ceis"), "20261113")
        self.assertEqual(federal.data_mais_recente(self.PAGINA, "CNEP"), "20261114")

    def test_mes_e_dia_de_um_digito_viram_dois(self):
        self.assertEqual(federal.data_mais_recente('arquivos.push({"ano" : "2026", "mes" : "3", "dia" : "7", "origem" : "CEIS"})', "ceis"), "20260307")

    def test_pagina_sem_arquivo_do_cadastro_e_erro(self):
        with self.assertRaises(ValueError):
            federal.data_mais_recente("<html>Human Verification</html>", "ceis")
        with self.assertRaises(ValueError):
            federal.data_mais_recente('arquivos.push({"ano" : "2026", "mes" : "11", "dia" : "13", "origem" : "CNEP"})', "ceis")

    @staticmethod
    def zip_de(arquivos: dict) -> bytes:
        b = io.BytesIO()
        with zipfile.ZipFile(b, "w") as z:
            for nome, conteudo in arquivos.items():
                z.writestr(nome, conteudo)
        return b.getvalue()

    def test_zip_com_um_csv_devolve_o_csv_sem_alterar(self):
        self.assertEqual(federal.csv_do_zip(self.zip_de({"20261113_CEIS.csv": b"a;b\r\n1;2\r\n"})), b"a;b\r\n1;2\r\n")

    def test_resposta_que_nao_e_zip_para_sem_contornar(self):
        with self.assertRaisesRegex(ValueError, "não devolveu um arquivo zip"):
            federal.csv_do_zip(b"<!DOCTYPE html><title>Human Verification</title>")

    def test_zip_com_mais_de_um_csv_ou_nenhum_e_recusado(self):
        with self.assertRaises(ValueError):
            federal.csv_do_zip(self.zip_de({"a.csv": b"1", "b.csv": b"2"}))
        with self.assertRaises(ValueError):
            federal.csv_do_zip(self.zip_de({"leiame.txt": b"1"}))


class TestExtracao(unittest.TestCase):
    def test_pj_vira_fornecedor_com_razao_social_da_receita_e_ocorrencia_provada(self):
        pasta = pasta_com(ceis=[linha(cod="10", doc=PJ, nome="Nome do Órgão", receita="EMPRESA EXEMPLO LTDA")])
        self.addCleanup(pasta.cleanup)
        saida, rel, _ = extrair_de(Path(pasta.name))
        (s,), (f,), (e,) = saida["sancoes"], saida["fornecedores"], saida["evidencias"]
        self.assertEqual((f["id"], f["cnpj"], f["tipo"], f["nome"], f["tenant"]), (f"cnpj:{PJ}", PJ, "PJ", "EMPRESA EXEMPLO LTDA", "br-uniao"))
        self.assertEqual((s["id"], s["cadastro"], s["tenant"], s["sensibilidade"]), ("br-uniao:ceis:10", "CEIS", "br-uniao", "publico"))
        self.assertEqual((s["publicada_em"], s["inicio_suspensao"], s["fim_suspensao"]), ("2018-11-05", "2018-11-22", "2028-11-22"))
        self.assertEqual((s["tipo"], s["orgao"], s["abrangencia"], s["situacao"]),
                         ("Impedimento/proibição de contratar com prazo determinado", "Ministério Exemplo", "Sem Informação", None))
        self.assertIn("Fundamentação: LEI 8666 ART 87", s["descricao"])
        self.assertEqual((s["fornecedor"], s["evidencia"]), (f["id"], e["id"]))
        self.assertEqual((rel["federal_pj"], rel["federal_pf"]), (1, 0))
        self.assertIn(f"CNPJ {PJ}", e["trecho"])                       # o CNPJ está no trecho: é o que a prova mostra
        self.assertIn("abrangência: Sem Informação", e["trecho"])
        self.assertEqual((e["tenant"], e["tabela"], e["capturado_em"], e["trecho_mascarado"]), ("br-uniao", "ceis", "2026-11-14", False))
        self.assertTrue(e["url"].endswith("/ceis/20261113"))
        self.assertNotIn("texto livre do portal", json.dumps(saida, ensure_ascii=False))    # a coluna de observações não entra

    def test_sem_razao_social_da_receita_usa_o_nome_do_sancionado(self):
        pasta = pasta_com(ceis=[linha(doc=PJ, nome="Nome Informado Ltda", receita="")])
        self.addCleanup(pasta.cleanup)
        self.assertEqual(extrair_de(Path(pasta.name))[0]["fornecedores"][0]["nome"], "Nome Informado Ltda")

    def test_pf_fica_so_como_hash_sem_nome_nem_documento(self):
        pasta = pasta_com(ceis=[linha(cod="20", doc=CPF, nome="Maria da Silva Exemplo")])
        self.addCleanup(pasta.cleanup)
        saida, rel, sensiveis = extrair_de(Path(pasta.name))
        (s,), (f,), (e,) = saida["sancoes"], saida["fornecedores"], saida["evidencias"]
        self.assertTrue(re.fullmatch(r"pf:[0-9a-f]{24}", f["id"]))
        self.assertEqual((f["tipo"], f["cnpj"], f["nome"]), ("PF", None, None))
        self.assertEqual((s["sensibilidade"], s["descricao"]), ("pessoal", None))
        self.assertTrue(e["trecho_mascarado"])
        texto = json.dumps(saida, ensure_ascii=False)
        for proibido in (CPF, "Maria da Silva", "Exemplo Ltda"):
            self.assertNotIn(proibido, texto)
        self.assertEqual((rel["federal_pf"], rel["federal_pj"]), (1, 0))
        self.assertIn(CPF, sensiveis)                                   # entra na trava de vazamento do main

    def test_pf_do_ceis_e_do_estado_tem_o_mesmo_hash(self):
        """O CPF do CEIS vem inteiro e o do painel do Estado perde o zero à esquerda: o hash precisa ser o mesmo."""
        cpf = cpf_com_zero_a_esquerda()
        self.assertTrue(cpf.startswith("0") and extrair.cpf_valido(cpf))
        pasta = pasta_com(ceis=[linha(doc=cpf)])
        self.addCleanup(pasta.cleanup)
        saida, _, _ = extrair_de(Path(pasta.name))
        self.assertEqual(saida["fornecedores"][0]["id"], f"pf:{extrair.pseudonimo(cpf.lstrip('0'))}")

    def test_cpf_colado_no_nome_de_mei_e_mascarado(self):
        pasta = pasta_com(ceis=[linha(doc=PJ, nome=f"JOSE EXEMPLO {CPF}", receita=f"JOSE EXEMPLO {CPF}")])
        self.addCleanup(pasta.cleanup)
        saida, _, _ = extrair_de(Path(pasta.name))
        self.assertNotIn(CPF, saida["evidencias"][0]["trecho"])
        self.assertEqual(extrair.sem_cpf(saida["fornecedores"][0]["nome"]), "JOSE EXEMPLO [CPF]")    # o main aplica esta passada nos nomes

    def test_codigo_repetido_conta_uma_vez_e_documento_invalido_e_descartado(self):
        pasta = pasta_com(ceis=[linha(cod="1", doc=PJ), linha(cod="1", doc=PJ), linha(cod="2", doc="12345678000100"), linha(cod="3", doc=PJ2)])
        self.addCleanup(pasta.cleanup)
        saida, rel, _ = extrair_de(Path(pasta.name))
        self.assertEqual([s["id"] for s in saida["sancoes"]], ["br-uniao:ceis:1", "br-uniao:ceis:3"])
        self.assertEqual((rel["federal_linha_repetida"], rel["federal_documento_invalido"], rel["federal_pj"]), (1, 1, 2))

    def test_linha_sem_codigo_e_contada_e_ignorada(self):
        pasta = pasta_com(ceis=[linha(cod="", doc=PJ)])
        self.addCleanup(pasta.cleanup)
        saida, rel, _ = extrair_de(Path(pasta.name))
        self.assertEqual((saida["sancoes"], rel["federal_sem_codigo"]), ([], 1))

    def test_cnep_traz_o_valor_da_multa_com_virgula_decimal(self):
        pasta = pasta_com(cnep=[linha(cadastro="CNEP", cod="7", doc=PJ, categoria="Multa", multa="7986,15", fim="")])
        self.addCleanup(pasta.cleanup)
        (s,) = extrair_de(Path(pasta.name))[0]["sancoes"]
        self.assertEqual((s["id"], s["cadastro"], s["valor_multa"], s["fim_suspensao"]), ("br-uniao:cnep:7", "CNEP", 7986.15, None))

    def test_ceis_sem_multa_fica_com_valor_nulo_e_data_final_vazia_fica_nula(self):
        pasta = pasta_com(ceis=[linha(fim="")])
        self.addCleanup(pasta.cleanup)
        (s,) = extrair_de(Path(pasta.name))[0]["sancoes"]
        self.assertEqual((s["valor_multa"], s["fim_suspensao"]), (None, None))

    def test_data_1900_do_portal_vira_nula(self):
        pasta = pasta_com(ceis=[linha(pub="01/01/1900")])
        self.addCleanup(pasta.cleanup)
        self.assertIsNone(extrair_de(Path(pasta.name))[0]["sancoes"][0]["publicada_em"])

    def test_arquivo_ausente_nao_faz_nada_e_um_so_cadastro_basta(self):
        pasta = pasta_com()
        self.addCleanup(pasta.cleanup)
        saida, rel, _ = extrair_de(Path(pasta.name))
        self.assertEqual((saida["sancoes"], dict(rel)), ([], {}))
        pasta2 = pasta_com(cnep=[linha(cadastro="CNEP", doc=PJ, multa="1,00")])
        self.addCleanup(pasta2.cleanup)
        self.assertEqual(len(extrair_de(Path(pasta2.name))[0]["sancoes"]), 1)

    def test_layout_que_mudou_para_em_vez_de_adivinhar(self):
        pasta = pasta_com()
        self.addCleanup(pasta.cleanup)
        (Path(pasta.name) / "federal-ceis.csv").write_bytes("CADASTRO;CODIGO;DOC\r\nCEIS;1;2\r\n".encode("cp1252"))
        with self.assertRaisesRegex(ValueError, "layout mudou"):
            extrair_de(Path(pasta.name))

    def test_cabecalho_sem_acento_tambem_vale(self):
        pasta = pasta_com()
        self.addCleanup(pasta.cleanup)
        sem_acento = CAB_CEIS.upper().replace("Ç", "C").replace("Ã", "A").replace("Á", "A").replace("Ó", "O").replace("Í", "I").replace("Ú", "U").replace("Õ", "O")
        (Path(pasta.name) / "federal-ceis.csv").write_bytes((sem_acento + "\r\n" + linha() + "\r\n").encode("cp1252"))
        self.assertEqual(len(extrair_de(Path(pasta.name))[0]["sancoes"]), 1)


class TestAmostra(unittest.TestCase):
    """Os 100 contratos não podem mudar por causa das sanções federais; as federais de PJ entram todas, as de PF nenhuma."""

    @staticmethod
    def base(com_federal: bool):
        contratos, fornecedores, evidencias = [], [], []
        for i in range(80):
            contratos.append({"id": f"pe-estado:c{i}", "tenant": "pe-estado", "sensibilidade": "publico", "fornecedor": f"cnpj:{i:014d}",
                              "valor_contratado": 1000.0 + i, "uj_nome": f"Órgão {i % 7}", "processo": None, "processo_informado": False, "tem_aditivo": False,
                              "evidencia": f"ev-c{i}"})
        for i in range(35):
            contratos.append({"id": f"pe-garanhuns:c{i}", "tenant": "pe-garanhuns", "sensibilidade": "publico", "fornecedor": f"cnpj:9{i:013d}",
                              "valor_contratado": 500.0 + i, "uj_nome": "Prefeitura", "processo": None, "processo_informado": False, "tem_aditivo": False,
                              "evidencia": f"ev-g{i}"})
        for c in contratos:
            evidencias.append({"id": c["evidencia"], "tenant": c["tenant"]})
            fornecedores.append({"id": c["fornecedor"], "tipo": "PJ", "tenant": c["tenant"], "evidencia": c["evidencia"], "nome": "x"})
        sancoes = [{"id": "pe-estado:sancao:1", "tenant": "pe-estado", "sensibilidade": "publico", "situacao": "EM ABERTO", "fornecedor": "cnpj:00000000000003", "evidencia": "ev-s1"}]
        evidencias.append({"id": "ev-s1", "tenant": "pe-estado"})
        if com_federal:
            # As dez federais caem nos fornecedores de MENOR valor do Estado: só entrariam na amostra se a sanção federal influísse na escolha.
            federais = [(f"cnpj:{i:014d}", "publico") for i in range(10)] + [(f"cnpj:{PJ}", "publico"), ("pf:abc", "pessoal")]
            for k, (forn, sens) in enumerate(federais):
                sancoes.append({"id": f"br-uniao:ceis:{k}", "tenant": "br-uniao", "sensibilidade": sens, "situacao": None, "fornecedor": forn, "evidencia": f"ev-f{k}"})
                fornecedores.append({"id": forn, "tipo": "PF" if sens == "pessoal" else "PJ", "tenant": "br-uniao", "evidencia": f"ev-f{k}", "nome": "y"})
                evidencias.append({"id": f"ev-f{k}", "tenant": "br-uniao"})
            contratos.append({"id": "br-uniao:contrato:f1", "tenant": "br-uniao", "sensibilidade": "publico", "fornecedor": f"cnpj:{PJ}", "valor_contratado": 9e9,
                              "uj_nome": "Unidade federal", "processo": None, "processo_informado": False, "tem_aditivo": None, "evidencia": "ev-fc"})
            evidencias.append({"id": "ev-fc", "tenant": "br-uniao"})
        return {"contratos": contratos, "processos": [], "fornecedores": fornecedores, "sancoes": sancoes, "execucoes": [], "evidencias": evidencias}

    def rodar(self, com_federal: bool) -> dict:
        pasta = tempfile.TemporaryDirectory()
        self.addCleanup(pasta.cleanup)
        dados = Path(pasta.name)
        for nome, itens in self.base(com_federal).items():
            (dados / f"{nome}.jsonl").write_text("".join(json.dumps(i, ensure_ascii=False) + "\n" for i in itens), encoding="utf-8")
        antes = (amostra.DADOS, amostra.SAIDA)
        amostra.DADOS, amostra.SAIDA = dados, dados / "amostra"
        try:
            with open(os.devnull, "w") as nulo, contextlib.redirect_stdout(nulo):
                amostra.main()
        finally:
            amostra.DADOS, amostra.SAIDA = antes
        return {n.stem: [json.loads(l) for l in n.read_text(encoding="utf-8").splitlines()] for n in (dados / "amostra").glob("*.jsonl")}

    def test_a_escolha_dos_contratos_nao_muda_com_as_sancoes_federais(self):
        sem, com = self.rodar(False), self.rodar(True)
        self.assertEqual([c["id"] for c in sem["contratos"]], [c["id"] for c in com["contratos"] if c["tenant"] != "br-uniao"])
        self.assertEqual(len([c for c in com["contratos"] if c["tenant"] != "br-uniao"]), 100)

    def test_entram_as_federais_de_pj_e_nenhuma_de_pf(self):
        com = self.rodar(True)
        federais = {s["id"] for s in com["sancoes"] if s["tenant"] == "br-uniao"}
        self.assertEqual(federais, {f"br-uniao:ceis:{k}" for k in range(11)})                  # as 11 de PJ; a 12ª, de PF, não
        forn_federais = {f["id"] for f in com["fornecedores"] if f["tenant"] == "br-uniao"}
        self.assertEqual(forn_federais, {f"cnpj:{i:014d}" for i in range(10)} | {f"cnpj:{PJ}"})
        ev = {e["id"] for e in com["evidencias"]}
        self.assertTrue({f"ev-f{k}" for k in range(11)} <= ev and "ev-f11" not in ev)
        self.assertEqual(sum(s["tenant"] == "pe-estado" for s in com["sancoes"]), 1)            # a estadual continua

    def test_o_contrato_federal_passa_inteiro_uma_vez_so_com_a_evidencia(self):
        com = self.rodar(True)
        self.assertEqual([c["id"] for c in com["contratos"] if c["tenant"] == "br-uniao"], ["br-uniao:contrato:f1"])
        self.assertIn("ev-fc", {e["id"] for e in com["evidencias"]})
        self.assertEqual(len(com["contratos"]), 101)

    def test_sem_federal_a_saida_e_a_de_antes(self):
        sem = self.rodar(False)
        self.assertEqual({s["tenant"] for s in sem["sancoes"]}, {"pe-estado"})


class TestPerfil(unittest.TestCase):
    def test_o_perfil_com_a_uniao_existe_e_os_antigos_nao_a_enxergam(self):
        p = perfis.carregar()
        self.assertEqual(set(p["estado-uniao"]["tenants"]), {"pe-estado", "pe-garanhuns", "br-uniao"})
        self.assertFalse(p["estado-uniao"]["ver_pessoal"])
        for antigo in ("municipio", "estado", "estado-exemplo"):
            self.assertNotIn("br-uniao", p[antigo]["tenants"])


if __name__ == "__main__":
    unittest.main()
