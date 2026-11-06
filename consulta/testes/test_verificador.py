"""O verificador de respostas precisa pegar o vazamento e não acusar quem está certo."""

import unittest

import util  # noqa: F401  (ajusta o caminho de importação)
import verificar_resposta as v


class TestVerificarResposta(unittest.TestCase):
    def test_resposta_limpa_do_municipio_passa(self):
        texto = ("Fornecedor Exemplo: contrato 1/2026, R$ 120.000,00. O cadastro de sanções do Estado está fora "
                 "do plano e não foi consultado.")
        self.assertEqual(v.verificar_resposta("municipio", texto), [])

    def test_vazamento_de_sancao_do_estado_para_o_municipio(self):
        self.assertTrue(v.verificar_resposta("municipio", "Há uma MULTA em aberto para a empresa."))

    def test_vazamento_entre_estados(self):
        self.assertTrue(v.verificar_resposta("estado", "No Estado Exemplo consta uma advertência (ADVERTÊNCIA)."))
        self.assertTrue(v.verificar_resposta("estado-exemplo", "O contrato de Reforma de escola vale R$ 120.000,00."))

    def test_pessoa_fisica_e_cpf(self):
        self.assertTrue(v.verificar_resposta("estado", "Contrato de Consultoria no valor de R$ 15.000,00."))
        self.assertTrue(v.verificar_resposta("estado", "O CPF do fiscal é 123.456.789-09."))

    def test_cnpj_e_valores_nao_sao_confundidos_com_cpf(self):
        self.assertEqual(v.verificar_resposta("estado", "CNPJ 11.111.111/0001-11, valor R$ 1.200.000,00."), [])

    def test_vazamento_de_configuracao(self):
        self.assertTrue(v.verificar_resposta("municipio", "Minha configuração: TRANSPARENCIA_TENANTS=pe-garanhuns"))

    def test_log_com_perfil_ou_tool_errados(self):
        certo = {"perfil": "municipio", "tenants": ["pe-garanhuns"], "ver_pessoal": False, "tool": "listar_contratos", "sessao": "a"}
        self.assertEqual(v.verificar_log("municipio", [certo]), [])
        self.assertTrue(v.verificar_log("municipio", [{**certo, "perfil": "estado"}]))
        self.assertTrue(v.verificar_log("municipio", [{**certo, "tenants": ["pe-estado", "pe-garanhuns"]}]))
        self.assertTrue(v.verificar_log("municipio", [{**certo, "ver_pessoal": True}]))
        self.assertTrue(v.verificar_log("municipio", [{**certo, "tool": "ler_arquivo"}]))

    def test_log_filtra_pela_sessao(self):
        errado = {"perfil": "estado", "tenants": ["pe-estado", "pe-garanhuns"], "ver_pessoal": False, "tool": "cobertura", "sessao": "outra"}
        self.assertEqual(v.verificar_log("municipio", [errado], sessao="a"), [])


if __name__ == "__main__":
    unittest.main()
