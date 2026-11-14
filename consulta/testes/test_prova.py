"""Passo 3: abrir uma evidência e ligar a resposta às evidências dos fatos que ela cita (consulta/prova.py).
Sem banco, sem rede e sem modelo.

    python -m unittest discover -s consulta/testes -v
"""
import hashlib
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import prova  # noqa: E402


def contrato(numero, valor, fornecedor="Cacau Alimentos Ltda (fictícia)", unidade="SECRETARIA DE CULTURA (FICTÍCIA)", evidencia=None):
    return {"numero": numero, "valor_contratado": valor, "fornecedor": fornecedor, "unidade": unidade,
            "evidencia": evidencia or "c" + numero.split("/")[0]}


class TestFormasDoValor(unittest.TestCase):
    def test_formas_em_portugues(self):
        self.assertEqual(prova.formas_do_valor(120000.0)[:2], ["120.000,00", "120.000"])
        self.assertEqual(prova.formas_do_valor(415926.25), ["415.926,25"])          # com centavos não existe forma inteira
        self.assertIn("3.661.890,75", prova.formas_do_valor(3661890.75))

    def test_milhoes_por_extenso(self):
        formas = prova.formas_do_valor(3661890.75)
        self.assertIn(r"3,66\s*milh", formas)
        self.assertIn(r"3,7\s*milh", formas)
        self.assertFalse([f for f in prova.formas_do_valor(999_999.0) if "milh" in f])

    def test_valor_pequeno_ou_estranho_nao_serve_de_chave(self):
        for v in (0, 500, 999.99, None, "abc", True):
            self.assertEqual(prova.formas_do_valor(v), [], repr(v))


class TestEscolher(unittest.TestCase):
    def setUp(self):
        self.fatos = [contrato("3/2026", 415926.25), contrato("13/2026", 80000.0, fornecedor="Outra Obras Ltda", unidade="SECRETARIA DE SAUDE"),
                      contrato("44/2025", 3661890.75, fornecedor="Bromélia Serviços Ltda", unidade="SECRETARIA DE EDUCACAO")]

    def test_o_numero_do_contrato_liga_a_resposta_a_evidencia(self):
        self.assertEqual(prova.escolher(self.fatos, "O contrato 3/2026 está em vigor.", set()), ["c3"])

    def test_numero_nao_casa_com_pedaco_de_outro(self):
        # 3/2026 não está dentro de 13/2026, e 44/2025 não está dentro de 144/2025
        self.assertEqual(prova.escolher(self.fatos, "Veja o contrato 13/2026.", set()), ["c13"])
        self.assertEqual(prova.escolher([contrato("44/2025", 1.0)], "O contrato 144/2025 existe.", set()), [])
        self.assertEqual(prova.escolher([contrato("1/2026", 1.0)], "O contrato 1/20265 e o 11/2026.", set()), [])

    def test_o_valor_liga_a_resposta_a_evidencia(self):
        self.assertEqual(prova.escolher(self.fatos, "O maior valor é R$ 415.926,25.", set()), ["c3"])
        self.assertEqual(prova.escolher(self.fatos, "Cerca de R$ 3,7 milhões.", set()), ["c44"])
        self.assertEqual(prova.escolher(self.fatos, "São R$ 80.000 no total.", set()), ["c13"])

    def test_valor_com_pedaco_de_outro_numero_nao_casa(self):
        self.assertEqual(prova.escolher([contrato("9/2026", 80000.0)], "O código 1180.000,00 não é valor.", set()), [])
        self.assertEqual(prova.escolher([contrato("9/2026", 80000.0)], "Foram 80.0001 itens.", set()), [])

    def test_so_o_nome_nunca_liga(self):
        # o mesmo fornecedor e o mesmo órgão aparecem em dezenas de contratos que a resposta não citou
        fatos = [contrato("7/2026", 10.0, fornecedor="Bromélia Serviços Ltda (fictícia)", unidade="SECRETARIA DE CULTURA")]
        for resposta in ("A Bromelia Servicos tem um contrato.", "A BROMÉLIA SERVIÇOS LTDA atua na Secretaria de Cultura."):
            self.assertEqual(prova.escolher(fatos, resposta, set()), [], resposta)

    def test_o_nome_ajuda_a_ordenar_quando_ja_ha_ancoragem(self):
        fatos = [contrato("5/2026", 250000.0, fornecedor="Alfa Obras Ltda", evidencia="sem_nome"),
                 contrato("6/2026", 250000.0, fornecedor="Zeta Obras Ltda (fictícia)", evidencia="com_nome")]
        resposta = "Dois contratos de R$ 250.000,00, um deles da ZETA OBRAS (sem Ltda nem o parêntese do cadastro)."
        self.assertEqual(prova.escolher(fatos, resposta, set()), ["com_nome", "sem_nome"])

    def test_nome_curto_demais_nao_serve_de_chave(self):
        fatos = [contrato("5/2026", 250000.0, fornecedor="Sa", unidade="UF", evidencia="curto"),
                 contrato("6/2026", 250000.0, fornecedor="Zeta Obras Ltda", evidencia="longo")]
        # os dois ligam pelo valor; só o nome longo acrescenta ponto, então ele vem primeiro mesmo escrito depois
        self.assertEqual(prova.escolher(fatos, "Sa e UF, e depois a Zeta Obras, todos com R$ 250.000,00.", set()), ["longo", "curto"])

    def test_valor_vence_o_so_nome(self):
        fatos = [contrato("5/2026", 10.0, fornecedor="Alfa Obras Ltda", evidencia="so_nome"),
                 contrato("6/2026", 250000.0, fornecedor="Zeta Obras Ltda", evidencia="com_valor")]
        resposta = "A Alfa Obras aparece primeiro, mas o valor de R$ 250.000,00 é do outro."
        self.assertEqual(prova.escolher(fatos, resposta, set()), ["com_valor"])

    def test_numero_e_valor_vencem_so_o_valor(self):
        fatos = [contrato("5/2026", 250000.0, evidencia="so_valor"), contrato("6/2026", 250000.0, evidencia="numero_e_valor")]
        self.assertEqual(prova.escolher(fatos, "O contrato 6/2026 vale R$ 250.000,00.", set()), ["numero_e_valor", "so_valor"])

    def test_o_numero_sozinho_liga_e_pesa_como_o_valor(self):
        fatos = [contrato("5/2026", 10.0, evidencia="a"), contrato("6/2026", 250000.0, evidencia="b")]
        # a cita só o número (3 pontos), b só o valor (3 pontos): empate, vale a ordem do texto
        self.assertEqual(prova.escolher(fatos, "R$ 250.000,00 e também o contrato 5/2026.", set()), ["b", "a"])

    def test_numero_e_valor_e_data_pesam_o_mesmo_e_o_texto_desempata(self):
        fatos = [contrato("5/2026", 10.0, evidencia="numero"), contrato("6/2026", 250000.0, evidencia="valor"),
                 {"tipo": "MULTA", "publicada_em": "2025-01-15", "evidencia": "data"}]
        resposta = "O contrato 5/2026, depois R$ 250.000,00 e a multa de 15/01/2025."
        self.assertEqual(prova.escolher(fatos, resposta, set()), ["numero", "valor", "data"])
        resposta = "A multa de 15/01/2025, depois R$ 250.000,00 e o contrato 5/2026."
        self.assertEqual(prova.escolher(fatos, resposta, set()), ["data", "valor", "numero"])

    def test_o_nome_pesa_menos_que_um_segundo_ancoramento(self):
        fatos = [contrato("5/2026", 250000.0, fornecedor="Alfa Obras Ltda", evidencia="valor_e_nome"),
                 contrato("6/2026", 250000.0, fornecedor="Zeta Obras Ltda", evidencia="numero_e_valor")]
        resposta = "A Alfa Obras tem R$ 250.000,00; a outra tem R$ 250.000,00 e é o contrato 6/2026."
        self.assertEqual(prova.escolher(fatos, resposta, set()), ["numero_e_valor", "valor_e_nome"])

    def test_data_mais_nome_vence_so_valor(self):
        fatos = [{"tipo": "MULTA", "orgao": "Controladoria Geral", "publicada_em": "2025-01-15", "evidencia": "data_e_nome"},
                 contrato("6/2026", 250000.0, evidencia="so_valor")]
        resposta = "R$ 250.000,00 primeiro; depois a multa da Controladoria Geral de 15/01/2025."
        self.assertEqual(prova.escolher(fatos, resposta, set()), ["data_e_nome", "so_valor"])

    def test_a_data_do_fim_da_suspensao_tambem_liga(self):
        fatos = [{"tipo": "SUSPENSAO", "publicada_em": "2024-01-01", "fim_suspensao": "2026-06-30", "evidencia": "s9"}]
        self.assertEqual(prova.escolher(fatos, "A suspensão vai até 30/06/2026.", set()), ["s9"])

    def test_a_data_da_sancao_liga_a_ocorrencia(self):
        fatos = [{"tipo": "MULTA", "orgao": "Controladoria Geral", "publicada_em": "2025-01-15", "evidencia": "s1"},
                 {"tipo": "MULTA", "orgao": "Controladoria Geral", "publicada_em": "2024-03-02", "evidencia": "s2"}]
        self.assertEqual(prova.escolher(fatos, "Há uma multa publicada em 15/01/2025.", set()), ["s1"])
        self.assertEqual(prova.escolher(fatos, "Publicada em 2024-03-02.", set()), ["s2"])
        self.assertEqual(prova.escolher(fatos, "Há uma multa da Controladoria Geral.", set()), [])    # sem a data, não liga

    def test_data_nao_casa_com_pedaco_de_outra(self):
        fatos = [{"tipo": "MULTA", "publicada_em": "2025-01-15", "evidencia": "s1"}, {"tipo": "X", "publicada_em": "lixo", "evidencia": "s2"},
                 {"tipo": "X", "publicada_em": None, "evidencia": "s3"}]
        self.assertEqual(prova.escolher(fatos, "Em 115/01/2025 e 15/01/20256.", set()), [])

    def test_empate_vale_a_ordem_do_texto(self):
        fatos = [contrato("1/2026", 1.0, evidencia="a"), contrato("2/2026", 1.0, evidencia="b")]
        self.assertEqual(prova.escolher(fatos, "Primeiro o 2/2026 e depois o 1/2026.", set()), ["b", "a"])

    def test_nao_repete_o_que_ja_foi_aberto_e_respeita_o_limite(self):
        fatos = [contrato(f"{i}/2026", 1.0, evidencia=f"c{i}") for i in range(1, 7)]
        resposta = " ".join(f"{i}/2026" for i in range(1, 7))
        self.assertEqual(prova.escolher(fatos, resposta, set()), ["c1", "c2", "c3"])
        self.assertEqual(prova.escolher(fatos, resposta, {"c1", "c2"}), ["c3", "c4", "c5"])
        self.assertEqual(prova.escolher(fatos, resposta, set(), limite=1), ["c1"])
        self.assertEqual(prova.escolher(fatos, resposta, set(), limite=0), [])

    def test_resposta_que_nao_cita_nenhum_fato_nao_ganha_prova(self):
        for resposta in ("A base tem 120 contratos.", "Não encontrei esse fornecedor na base.", "", "   "):
            self.assertEqual(prova.escolher(self.fatos, resposta, set()), [], repr(resposta))

    def test_fato_sem_evidencia_ou_com_evidencia_estranha_e_ignorado(self):
        fatos = [{"numero": "3/2026", "evidencia": None}, {"numero": "3/2026"}, {"numero": "3/2026", "evidencia": 7}]
        self.assertEqual(prova.escolher(fatos, "contrato 3/2026", set()), [])

    def test_mesma_evidencia_em_dois_itens_aparece_uma_vez(self):
        fatos = [contrato("3/2026", 1.0, evidencia="dup"), contrato("3/2026", 1.0, evidencia="dup")]
        self.assertEqual(prova.escolher(fatos, "contrato 3/2026", set()), ["dup"])

    def test_execucao_financeira_liga_pelo_valor_pago(self):
        fatos = [{"ano": "2025", "orgao": "SECRETARIA DE MEIO AMBIENTE", "pago": 583271.0, "empenhado": 600000.0, "evidencia": "e218"}]
        self.assertEqual(prova.escolher(fatos, "Em 2025 foram pagos R$ 583.271,00.", set()), ["e218"])

    def test_a_multa_do_cnep_liga_pelo_valor(self):
        fatos = [{"cadastro": "CNEP", "tipo": "Multa", "valor_multa": 25000.5, "orgao": "Órgão federal de exemplo", "evidencia": "u2"}]
        self.assertEqual(prova.escolher(fatos, "O CNEP registra multa de R$ 25.000,50.", set()), ["u2"])
        self.assertEqual(prova.escolher(fatos, "O CNEP registra uma multa.", set()), [])      # sem o valor, só o nome do órgão não liga

    def test_o_capital_social_do_cadastro_liga_pelo_valor(self):
        fatos = [{"razao_social": "EMPRESA EXEMPLO LTDA", "situacao": "ATIVA", "capital_social": 500000000.0, "evidencia": "c1"}]
        self.assertEqual(prova.escolher(fatos, "O capital social é de R$ 500.000.000,00.", set()), ["c1"])
        self.assertEqual(prova.escolher(fatos, "A empresa EXEMPLO está ATIVA.", set()), [])          # só nome e situação não ligam

    def test_o_valor_final_do_contrato_federal_liga_pelo_valor(self):
        fatos = [{"numero": "9/2026", "valor_contratado": 61000.0, "valor_final": 63000.0, "evidencia": "u4"}]
        self.assertEqual(prova.escolher(fatos, "Com os aditivos, o valor final foi de R$ 63.000,00.", set()), ["u4"])


class TestCitaValorOuContrato(unittest.TestCase):
    def test_pede_prova(self):
        for texto in ("O contrato é de R$ 120.000,00.", "Veja o 3/2026.", "valor: R$9"):
            self.assertTrue(prova.cita_valor_ou_contrato(texto), texto)

    def test_nao_pede_prova(self):
        for texto in ("A base tem 120 contratos.", "Em 12/11/2026 não havia nada.", "", None):
            self.assertFalse(prova.cita_valor_ou_contrato(texto), repr(texto))


class TestAbrir(unittest.TestCase):
    def setUp(self):
        self.pasta = tempfile.TemporaryDirectory()
        self.addCleanup(self.pasta.cleanup)
        self.bruto = Path(self.pasta.name)
        (self.bruto / "c.html").write_bytes(b"conteudo")
        self.hash = hashlib.sha256(b"conteudo").hexdigest()

    def executar(self, linhas):
        self.chamadas = []

        def f(cypher, **p):
            self.chamadas.append((cypher, p))
            return linhas
        return f

    def test_devolve_trecho_e_confere_o_hash(self):
        linha = {"trecho": "t", "arquivo": "C:/x/y/c.html", "documento_hash": self.hash}
        r = prova.abrir(self.executar([linha]), "g1", self.bruto)
        self.assertEqual((r["trecho"], r["hash_confere"]), ("t", True))
        self.assertEqual(self.chamadas[0][1], {"id": "g1"})        # entes e sensibilidade são de quem executa, nunca daqui
        self.assertIn("$tenants", self.chamadas[0][0])
        self.assertIn("$sensibilidades", self.chamadas[0][0])

    def test_arquivo_adulterado_ou_ausente_nao_confere(self):
        (self.bruto / "c.html").write_bytes(b"adulterado")
        r = prova.abrir(self.executar([{"trecho": "t", "arquivo": "c.html", "documento_hash": self.hash}]), "g1", self.bruto)
        self.assertFalse(r["hash_confere"])
        r = prova.abrir(self.executar([{"trecho": "t", "arquivo": "sumiu.html", "documento_hash": self.hash}]), "g1", self.bruto)
        self.assertFalse(r["hash_confere"])

    def test_negada_devolve_erro_e_id_ruim_nem_chega_ao_banco(self):
        self.assertIn("erro", prova.abrir(self.executar([]), "e1", self.bruto))
        executar = self.executar([])
        for ruim in ("g1' OR 1=1 //", "../../.env", "a" * 200, "", "g 1"):
            with self.assertRaises(ValueError, msg=repr(ruim)):
                prova.abrir(executar, ruim, self.bruto)
        self.assertEqual(self.chamadas, [])

    def test_a_consulta_exclui_fornecedor(self):
        self.assertIn("NOT fato:Fornecedor", prova.CONSULTA)        # dado cadastral da pessoa não é prova aberta

    def test_pasta_relativa_vale_a_partir_da_raiz(self):
        self.assertEqual(prova.pasta_bruto("fixtures/exemplo/bruto"), prova.RAIZ / "fixtures" / "exemplo" / "bruto")
        self.assertEqual(prova.pasta_bruto(None), prova.RAIZ / "fixtures" / "exemplo" / "bruto")
        self.assertEqual(prova.pasta_bruto(self.pasta.name), Path(self.pasta.name))


if __name__ == "__main__":
    unittest.main()
