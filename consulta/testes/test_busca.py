"""Passo 4: a consulta do índice de texto (consulta/busca.py). Sem banco, sem rede e sem modelo.

    python -m unittest discover -s consulta/testes -v
"""
import random
import re
import string
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import busca  # noqa: E402

# O que pode aparecer numa consulta montada por nós: palavras minúsculas, parênteses, * e ~1, e os operadores em maiúsculas.
SO_O_NOSSO = re.compile(r"^(?:[a-z0-9]+|\(|\)|\*|~1|AND|OR| )+$")

ATAQUES = [
    'x" OR 1=1', "a* OR b*", "NOT bromelia", "bromelia AND NOT cacau", "-bromelia +cacau", "bromelia^10", "(bromelia", "bromelia)))",
    "nome:bromelia", "fornecedor_nome:*", "/.*/", "bromelia~", "bromelia~0.1", "{a TO z}", "[a TO z]", "a\\b", "\\", "*:*", "?????",
    "x' }) MATCH (n) DETACH DELETE n //", "../../.env", "‮bromelia", "bromelia\x00cacau", "bromelia\ncacau",
]


class TestPalavras(unittest.TestCase):
    def test_minuscula_sem_acento_e_so_letras_e_digitos(self):
        self.assertEqual(busca.palavras("Bromélia Serviços-Gerais, LTDA (fictícia)"), ["bromelia", "servicos", "gerais", "ltda", "ficticia"])

    def test_palavra_de_uma_letra_cai(self):
        self.assertEqual(busca.palavras("a b cacau"), ["cacau"])

    def test_limite_de_palavras(self):
        self.assertEqual(len(busca.palavras(" ".join(["abcde"] * 20))), busca.MAX_PALAVRAS)

    def test_cnpj_vira_uma_palavra_de_digitos(self):
        self.assertEqual(busca.palavras("90.000.002/0001-17"), ["90", "000", "002", "0001", "17"])


class TestParaLucene(unittest.TestCase):
    def test_palavra_longa_casa_inteira_por_prefixo_ou_com_um_erro(self):
        self.assertEqual(busca.para_lucene("Bromélia"), "(bromelia* OR bromelia~1)")

    def test_palavra_media_so_por_prefixo_e_curta_so_inteira(self):
        self.assertEqual(busca.para_lucene("Sao Paulo da"), "sao* AND (paulo* OR paulo~1) AND da")

    def test_todas_as_palavras_tem_de_aparecer(self):
        self.assertEqual(busca.para_lucene("zeta omega"), "zeta* AND (omega* OR omega~1)")

    def test_sem_palavra_nao_ha_consulta(self):
        for vazio in ("", "   ", "!!!", "- + * ?", "a", None, "‮"):
            self.assertIsNone(busca.para_lucene(vazio), repr(vazio))

    def test_nenhum_ataque_leva_sintaxe_do_lucene_para_o_indice(self):
        for ataque in ATAQUES:
            q = busca.para_lucene(ataque)
            if q is not None:
                self.assertRegex(q, SO_O_NOSSO, ataque)
                for proibido in '"+-!{}[]^:\\/?&|':
                    self.assertNotIn(proibido, q, f"{ataque!r} -> {q!r}")

    def test_operador_escrito_pelo_usuario_vira_palavra_comum(self):
        # "AND", "OR" e "NOT" digitados pelo usuário são minúsculos e curtos: viram palavras, nunca operadores
        q = busca.para_lucene("bromelia OR cacau NOT ltda")
        self.assertEqual(q, "(bromelia* OR bromelia~1) AND or AND (cacau* OR cacau~1) AND not* AND ltda*")
        self.assertNotIn(" NOT ", q)

    def test_texto_aleatorio_nunca_gera_sintaxe_estranha(self):
        gerador = random.Random(7)
        alfabeto = string.printable + "áéíóúçãõâêôÁÉ‮\u0000"
        for _ in range(500):
            texto = "".join(gerador.choice(alfabeto) for _ in range(gerador.randint(0, 60)))
            q = busca.para_lucene(texto)
            if q is not None:
                self.assertRegex(q, SO_O_NOSSO, repr(texto))


if __name__ == "__main__":
    unittest.main()
