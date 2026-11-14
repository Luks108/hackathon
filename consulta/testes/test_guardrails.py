"""Testes das proteções do servidor MCP que não dependem de banco nem de modelo.

    python -m unittest discover -s consulta/testes -v

Cada teste cita o ataque do catálogo (docs/seguranca/ataques-de-prompt.md) que ele cobre.
O banco é substituído por um falso que grava a consulta que chegaria ao Neo4j.
"""

import asyncio
import json
import tempfile
import unittest
from pathlib import Path

import util
from util import DriverFalso, trocar_banco

# Nomes que NÃO podem existir como argumento de tool: o que o modelo não pode informar, o ataque não muda.
PROIBIDOS = {"tenant", "tenants", "ente", "entes", "perfil", "plano", "sensibilidade", "sensibilidades",
             "ver_pessoal", "cypher", "query", "consulta", "sql", "admin", "usuario", "limite"}

PAYLOADS_DE_ID = [
    "x' }) MATCH (n) DETACH DELETE n //",
    "cnpj:11111111000111' OR 1=1 //",
    "cnpj:11111111000111 }) RETURN 1 //",
    "../../.env",
    "pe-estado",                                   # nome de ente no lugar de um id
    "cnpj:" + "1" * 200,                           # tamanho absurdo
    "",
    "   ",
]


LINHA_QUALQUER = {"id": "cnpj:11111111000111", "contratos": 1, "sancoes": 0, "de": "2026-11-05", "ate": "2026-11-05",
                  "arquivo": "exemplo.html", "documento_hash": "0" * 64, "n": 0}


def servidor(perfil="municipio", **kw):
    return trocar_banco(util.carregar_servidor(perfil, **kw), [LINHA_QUALQUER])


class TestPerfilForaDoAlcanceDoModelo(unittest.TestCase):
    """AP-02, AP-03: o modelo não consegue informar nem mudar entes ou permissões."""

    def test_nenhuma_tool_aceita_argumento_de_perfil(self):
        mod = servidor()
        tools = asyncio.run(mod.mcp.list_tools())
        self.assertGreaterEqual(len(tools), 6)
        for t in tools:
            esquema = getattr(t, "input_schema", None) or getattr(t, "inputSchema", None) or {}
            nomes = set(esquema.get("properties", {}))
            self.assertFalse(nomes & PROIBIDOS, f"{t.name} aceita argumento proibido: {nomes & PROIBIDOS}")

    def test_passar_ente_por_argumento_falha(self):
        mod = servidor()
        with self.assertRaises(TypeError):
            mod.listar_contratos(tenants=["pe-estado"])
        with self.assertRaises(TypeError):
            mod.sancoes_do_fornecedor("cnpj:11111111000111", tenants=["pe-estado"])

    def test_argumento_de_ente_pelo_protocolo_e_ignorado(self):
        """Pelo protocolo MCP (como o agente chama), um argumento que a tool não tem é descartado: o filtro segue o ambiente."""
        mod = servidor("municipio")
        asyncio.run(mod.mcp.call_tool("listar_contratos", {"tenants": ["pe-estado", "ex-estado"], "sensibilidades": ["pessoal"]}))
        asyncio.run(mod.mcp.call_tool("sancoes_do_fornecedor", {"fornecedor_id": "cnpj:11111111000111", "tenants": ["ex-estado"]}))
        self.assertGreaterEqual(len(mod.driver.chamadas), 2)
        for _, params in mod.driver.chamadas:
            self.assertEqual(params["tenants"], ["pe-garanhuns"])
            self.assertEqual(params["sensibilidades"], ["publico"])

    def test_entes_da_consulta_vem_do_ambiente(self):
        for perfil, esperado in [("municipio", ["pe-garanhuns"]), ("estado", ["pe-estado", "pe-garanhuns"]),
                                 ("estado-exemplo", ["ex-estado"])]:
            mod = servidor(perfil)
            mod.listar_contratos()
            _, params = mod.driver.chamadas[-1]
            self.assertEqual(params["tenants"], esperado, perfil)

    def test_dado_pessoal_so_com_a_chave_do_ambiente(self):
        mod = servidor("municipio")
        mod.listar_contratos()
        self.assertEqual(mod.driver.chamadas[-1][1]["sensibilidades"], ["publico"])
        mod = servidor("municipio", ambiente={"TRANSPARENCIA_VER_PESSOAL": "sim"})
        mod.listar_contratos()
        self.assertEqual(mod.driver.chamadas[-1][1]["sensibilidades"], ["publico", "pessoal"])

    def test_sem_perfil_o_servidor_falha_fechado(self):
        mod = servidor(None)
        mod.listar_contratos()
        self.assertEqual(mod.driver.chamadas[-1][1]["tenants"], [])

    def test_perfil_desconhecido_nao_cai_num_padrao(self):
        with self.assertRaises(ValueError):
            util.perfis.ambiente("administrador")
        with self.assertRaises(ValueError):
            util.perfis.config_mcp("pe-estado")


class TestConsultasParametrizadas(unittest.TestCase):
    """AP-08: nenhum texto vindo do modelo é colado numa consulta."""

    def test_busca_por_texto_vai_como_parametro(self):
        mod = servidor()
        hostil = "x' }) MATCH (n) DETACH DELETE n //"
        mod.buscar_fornecedor(hostil)
        cypher, params = mod.driver.chamadas[-1]
        self.assertNotIn("DETACH", cypher)
        self.assertNotIn(hostil, cypher)
        # o texto do usuário não chega ao índice como veio: vira só palavras (consulta/busca.py), e vai como parâmetro
        self.assertNotIn(hostil, params.values())
        self.assertRegex(params["texto"], r"^[a-z0-9()*~ ANDOR]+$")
        for perigoso in "'}{\"/:;":
            self.assertNotIn(perigoso, params["texto"])

    def test_busca_devolve_no_maximo_10_sem_repetir_e_o_indice_traz_mais_que_o_limite_final(self):
        mod = trocar_banco(util.carregar_servidor("estado"), [{"id": f"cnpj:{i:014d}", "nome": f"Empresa {i}"} for i in range(12)])
        achados = mod.buscar_fornecedor("Empresa 11.111.111/0001-11")      # com dígitos: as duas consultas devolvem as mesmas linhas
        self.assertEqual(len(achados), 10)
        self.assertEqual(len({a["id"] for a in achados}), 10)
        self.assertGreaterEqual(mod.LIMITE_DO_INDICE, mod.LIMITE_LINHAS)    # o índice precisa trazer, antes do filtro de ente, mais do que sobra depois

    def test_buscas_filtram_ente_e_pessoa_fisica_depois_do_indice(self):
        mod = servidor("estado")
        mod.buscar_fornecedor("Construtora 11.111.111/0001-11")
        mod.buscar_contratos("reforma")
        for cypher, params in mod.driver.chamadas:
            self.assertIn("$tenants", cypher)
            if "fornecedor_nome" in cypher or "f.cnpj" in cypher:
                self.assertIn("size($sensibilidades) > 1", cypher)         # só PJ, salvo perfil com dado pessoal
            if "contrato_objeto" in cypher:
                self.assertIn("c.sensibilidade IN $sensibilidades", cypher)
        self.assertEqual(len(mod.driver.chamadas), 3)                      # CNPJ, nome e contrato

    def test_busca_sem_palavra_nao_consulta_o_indice(self):
        mod = servidor()
        self.assertEqual(mod.buscar_contratos("!!! ??? *"), [])
        self.assertEqual(mod.driver.chamadas, [])

    def test_todas_as_consultas_usam_parametros_de_perfil(self):
        mod = servidor()
        mod.cobertura()
        mod.buscar_fornecedor("Construtora")
        mod.listar_contratos()
        mod.contratos_do_fornecedor("cnpj:11111111000111")
        mod.sancoes_do_fornecedor("cnpj:11111111000111")
        mod.conferir_evidencia("g1")
        for cypher, params in mod.driver.chamadas:
            self.assertIn("$tenants", cypher, "consulta sem filtro de ente: " + cypher[:80])
            self.assertIn("tenants", params)

    def test_ids_maliciosos_nao_chegam_ao_banco(self):
        for tool in ("contratos_do_fornecedor", "sancoes_do_fornecedor"):
            for p in PAYLOADS_DE_ID:
                mod = servidor()
                with self.assertRaises(ValueError, msg=f"{tool}({p!r})"):
                    getattr(mod, tool)(p)
                self.assertEqual(mod.driver.chamadas, [], f"{tool}({p!r}) chegou ao banco")

    def test_evidencia_com_formato_invalido_nao_chega_ao_banco(self):
        for p in ["g1' OR 1=1 //", "../../etc/passwd", "a" * 200, "", "g 1"]:
            mod = servidor()
            with self.assertRaises(ValueError, msg=repr(p)):
                mod.conferir_evidencia(p)
            self.assertEqual(mod.driver.chamadas, [])

    def test_busca_vazia_ou_gigante_e_recusada(self):
        mod = servidor()
        for p in ["", "   ", "x" * 101]:
            with self.assertRaises(ValueError):
                mod.buscar_fornecedor(p)
        self.assertEqual(mod.driver.chamadas, [])


class TestLimitesDeSaida(unittest.TestCase):
    """AP-15: uma consulta não devolve a base inteira."""

    def test_listas_tem_limite(self):
        mod = servidor()
        mod.listar_contratos()
        mod.contratos_do_fornecedor("cnpj:11111111000111")
        mod.sancoes_do_fornecedor("cnpj:11111111000111")
        for cypher, params in mod.driver.chamadas:
            self.assertIn("LIMIT $limite", cypher)
            self.assertEqual(params["limite"], 50)


class TestRegistroDeConsultas(unittest.TestCase):
    """Requisito do desafio: registro de consultas e fontes."""

    def setUp(self):
        self.pasta = tempfile.TemporaryDirectory()
        self.log = Path(self.pasta.name) / "consultas.jsonl"
        self.addCleanup(self.pasta.cleanup)

    def linhas(self):
        return [json.loads(l) for l in self.log.read_text(encoding="utf-8").splitlines()]

    def test_cada_chamada_gera_uma_linha_com_perfil_e_evidencias(self):
        mod = util.carregar_servidor("estado", log=self.log, ambiente={"TRANSPARENCIA_SESSAO": "pergunta-7"})
        trocar_banco(mod, [{"numero": "1/2026", "evidencia": "g1"}, {"numero": "2/2026", "evidencia": "g2"}])
        mod.listar_contratos()
        reg = self.linhas()
        self.assertEqual(len(reg), 1)
        r = reg[0]
        self.assertEqual((r["perfil"], r["tool"], r["resultados"], r["sessao"]), ("estado", "listar_contratos", 2, "pergunta-7"))
        self.assertEqual(r["tenants"], ["pe-estado", "pe-garanhuns"])
        self.assertEqual(r["evidencias"], ["g1", "g2"])
        self.assertFalse(r["ver_pessoal"])
        self.assertIsNone(r["erro"])
        self.assertIn("ts", r)

    def test_cpf_digitado_na_busca_e_mascarado_no_log(self):
        mod = util.carregar_servidor("municipio", log=self.log)
        trocar_banco(mod, [])
        mod.buscar_fornecedor("João 123.456.789-09 e 98765432100")
        texto = self.log.read_text(encoding="utf-8")
        self.assertNotIn("123.456.789-09", texto)
        self.assertNotIn("98765432100", texto)
        self.assertIn("[CPF]", texto)

    def test_cnpj_nao_e_confundido_com_cpf(self):
        mod = util.carregar_servidor("municipio", log=self.log)
        trocar_banco(mod, [])
        mod.buscar_fornecedor("11.111.111/0001-11")
        self.assertIn("11.111.111/0001-11", self.linhas()[0]["args"]["termo"])

    def test_tentativa_recusada_tambem_e_registrada(self):
        mod = util.carregar_servidor("municipio", log=self.log)
        trocar_banco(mod, [])
        with self.assertRaises(ValueError):
            mod.contratos_do_fornecedor("x' }) DETACH DELETE n //")
        r = self.linhas()[0]
        self.assertTrue(r["erro"].startswith("ValueError"))
        self.assertEqual(r["resultados"], 0)

    def test_evidencia_negada_conta_zero_resultados(self):
        mod = util.carregar_servidor("municipio", log=self.log)
        trocar_banco(mod, [])
        out = mod.conferir_evidencia("e1")
        self.assertIn("erro", out)
        self.assertEqual(self.linhas()[0]["resultados"], 0)

    def test_falha_do_log_nao_derruba_a_consulta(self):
        arquivo = Path(self.pasta.name) / "arquivo"
        arquivo.write_text("x")
        mod = util.carregar_servidor("municipio", log=arquivo / "sub" / "consultas.jsonl")  # pai é um arquivo
        trocar_banco(mod, [])
        self.assertEqual(mod.listar_contratos(), [])


class TestPerfis(unittest.TestCase):
    def test_configuracao_tem_um_unico_servidor(self):
        cfg = util.perfis.config_mcp("estado", sessao="p1")
        self.assertEqual(list(cfg["mcpServers"]), ["transparencia"])
        env = cfg["mcpServers"]["transparencia"]["env"]
        self.assertEqual(env["TRANSPARENCIA_TENANTS"], "pe-estado,pe-garanhuns")
        self.assertEqual(env["TRANSPARENCIA_VER_PESSOAL"], "nao")
        self.assertEqual(env["TRANSPARENCIA_SESSAO"], "p1")

    def test_nenhum_perfil_padrao_enxerga_dado_pessoal(self):
        for nome, p in util.perfis.carregar().items():
            self.assertFalse(p["ver_pessoal"], nome)

    def test_municipio_nao_inclui_o_estado(self):
        self.assertNotIn("pe-estado", util.perfis.carregar()["municipio"]["tenants"])


if __name__ == "__main__":
    unittest.main()
