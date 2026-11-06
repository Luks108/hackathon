"""Isolamento entre perfis contra um Neo4j de verdade, com os dados fictícios de fixtures/exemplo.

    docker compose --env-file .env -f infra/docker-compose.yml up -d neo4j
    python coleta/carregar_neo4j.py --zerar --exemplo
    python -m unittest discover -s consulta/testes -v

Sem o banco no ar, estes testes são pulados (e dizem por quê).

O que fica provado aqui é o filtro de dados, que é a camada que o modelo não consegue alterar:
cada perfil chama as mesmas ferramentas e recebe só o que o seu ambiente permite.
"""

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

import util

A = "cnpj:11111111000111"      # Construtora Exemplo: aparece em pe-garanhuns, pe-estado e ex-estado
B = "cnpj:22222222000122"      # Serviços Modelo: só em pe-garanhuns (um contrato tem texto malicioso)
C = "cnpj:33333333000133"      # Obras Exemplares: só em ex-estado
PF = "pf:0123456789abcdef01234567"


def banco_disponivel() -> str | None:
    """Devolve o motivo de não poder testar, ou None se o banco está no ar com os dados de exemplo."""
    try:
        mod = util.carregar_servidor("municipio")
        try:
            n = mod.consultar("MATCH (e:Evidencia {id: 'g1'}) RETURN count(e) AS n")[0]["n"]
        finally:
            mod.driver.close()
    except Exception as erro:  # noqa: BLE001 - qualquer falha de conexão vira "pulado"
        return f"Neo4j indisponível ({type(erro).__name__}). Suba o banco e rode coleta/carregar_neo4j.py --zerar --exemplo"
    return None if n else "Neo4j no ar, mas sem os dados de exemplo. Rode coleta/carregar_neo4j.py --zerar --exemplo"


MOTIVO = banco_disponivel()


@unittest.skipIf(MOTIVO, MOTIVO or "")
class TestIsolamentoEntrePerfis(unittest.TestCase):
    def setUp(self):
        self.pasta = tempfile.TemporaryDirectory()
        self.addCleanup(self.pasta.cleanup)
        self.log = Path(self.pasta.name) / "consultas.jsonl"
        self.abertos = []
        self.addCleanup(lambda: [m.driver.close() for m in self.abertos])

    def perfil(self, nome, **ambiente):
        mod = util.carregar_servidor(nome, log=self.log, ambiente=ambiente)
        self.abertos.append(mod)
        return mod

    # ---------- Município: só pe-garanhuns ----------

    def test_municipio_ve_so_garanhuns_e_sem_pessoa_fisica(self):
        m = self.perfil("municipio")
        numeros = sorted(c["numero"] for c in m.listar_contratos())
        self.assertEqual(numeros, ["1/2026", "2/2026", "4/2026"])            # 3/2026 é pessoa física
        self.assertEqual(m.sancoes_do_fornecedor(A), [])                     # a multa é do Estado
        self.assertEqual(len(m.contratos_do_fornecedor(A)), 1)
        self.assertEqual(m.contratos_do_fornecedor(PF), [])
        cob = m.cobertura()
        self.assertEqual((cob["contratos"], cob["sancoes"], cob["tenants_do_perfil"]), (3, 0, ["pe-garanhuns"]))

    def test_municipio_nao_abre_evidencia_de_outro_ente_nem_de_pessoa(self):
        m = self.perfil("municipio")
        self.assertNotIn("erro", m.conferir_evidencia("g1"))
        for negada in ("e1", "x1", "x2", "g4"):                              # Estado, outro estado, pessoa física
            self.assertIn("erro", m.conferir_evidencia(negada), negada)

    def test_municipio_nao_encontra_fornecedor_de_outro_estado(self):
        m = self.perfil("municipio")
        self.assertEqual([f["id"] for f in m.buscar_fornecedor("Construtora")], [A])
        self.assertEqual(m.buscar_fornecedor("Obras Exemplares"), [])
        self.assertEqual(m.buscar_fornecedor("33333333000133"), [])
        self.assertEqual(m.contratos_do_fornecedor(C), [])

    # ---------- Estado: pe-estado + pe-garanhuns ----------

    def test_estado_ve_a_sancao_de_pe_e_nao_a_de_outro_estado(self):
        e = self.perfil("estado")
        sancoes = e.sancoes_do_fornecedor(A)
        self.assertEqual([(s["ente"], s["tipo"]) for s in sancoes], [("pe-estado", "MULTA")])
        self.assertEqual(e.cobertura()["sancoes"], 1)
        self.assertNotIn("erro", e.conferir_evidencia("e1"))
        self.assertIn("erro", e.conferir_evidencia("x1"))

    def test_estado_continua_sem_ver_pessoa_fisica(self):
        e = self.perfil("estado")
        self.assertEqual(len(e.listar_contratos()), 3)
        self.assertIn("erro", e.conferir_evidencia("g4"))
        self.assertEqual(e.buscar_fornecedor("pf"), [])

    # ---------- Outro estado (fictício): isolamento por estado ----------

    def test_outro_estado_so_ve_o_proprio_ente(self):
        x = self.perfil("estado-exemplo")
        self.assertEqual([c["numero"] for c in x.listar_contratos()], ["1/2026"])
        self.assertEqual([(s["ente"], s["tipo"]) for s in x.sancoes_do_fornecedor(A)], [("ex-estado", "ADVERTÊNCIA")])
        self.assertEqual(x.contratos_do_fornecedor(A), [])                   # o contrato de Garanhuns fica oculto
        for ok in ("x1", "x2"):
            self.assertNotIn("erro", x.conferir_evidencia(ok), ok)
        for negada in ("g1", "e1"):
            self.assertIn("erro", x.conferir_evidencia(negada), negada)
        self.assertEqual(x.buscar_fornecedor("Serviços Modelo"), [])

    def test_mesmo_cnpj_nao_vaza_fato_entre_estados(self):
        """O CNPJ A existe nos três entes. Cada perfil vê só as sanções do(s) seu(s) ente(s)."""
        vistas = {n: {s["ente"] for s in self.perfil(n).sancoes_do_fornecedor(A)}
                  for n in ("municipio", "estado", "estado-exemplo")}
        self.assertEqual(vistas, {"municipio": set(), "estado": {"pe-estado"}, "estado-exemplo": {"ex-estado"}})

    # ---------- A única chave do dado pessoal é o ambiente ----------

    def test_dado_pessoal_so_aparece_com_a_chave_do_ambiente(self):
        com = self.perfil("municipio", TRANSPARENCIA_VER_PESSOAL="sim")
        self.assertEqual(len(com.listar_contratos()), 4)
        self.assertNotIn("erro", com.conferir_evidencia("g4"))
        sem = self.perfil("municipio")
        self.assertEqual(len(sem.listar_contratos()), 3)

    def test_nenhum_perfil_padrao_devolve_dado_pessoal(self):
        for nome in util.perfis.carregar():
            mod = self.perfil(nome)
            texto = json.dumps(mod.listar_contratos(), ensure_ascii=False)
            self.assertNotIn("pf:", texto, nome)
            self.assertNotIn("Consultoria", texto, nome)

    # ---------- Texto do portal é dado ----------

    def test_texto_malicioso_do_portal_volta_como_dado_inerte(self):
        m = self.perfil("municipio")
        antes = sorted(c["numero"] for c in m.listar_contratos())
        achados = m.contratos_do_fornecedor(B)
        malicioso = [c for c in achados if "INSTRUÇÃO PARA O ASSISTENTE" in (c["objeto"] or "")]
        self.assertEqual(len(malicioso), 1)
        self.assertIsInstance(malicioso[0]["objeto"], str)
        # Ler o texto não muda nada: o perfil e os dados visíveis são os mesmos de antes.
        self.assertEqual(sorted(c["numero"] for c in m.listar_contratos()), antes)
        self.assertEqual(m.sancoes_do_fornecedor(A), [])
        self.assertEqual(m.cobertura()["tenants_do_perfil"], ["pe-garanhuns"])

    # ---------- Entrada hostil ----------

    def test_entrada_hostil_nao_altera_o_banco_nem_vaza(self):
        m = self.perfil("municipio")
        antes = m.consultar("MATCH (n) RETURN count(n) AS n")[0]["n"]
        self.assertEqual(m.buscar_fornecedor("x' }) MATCH (n) DETACH DELETE n //"), [])
        self.assertEqual(m.buscar_fornecedor("' OR 1=1 //"), [])
        with self.assertRaises(ValueError):
            m.contratos_do_fornecedor(A + "' }) MATCH (n) DETACH DELETE n //")
        self.assertEqual(m.consultar("MATCH (n) RETURN count(n) AS n")[0]["n"], antes)

    # ---------- Prova: o hash da evidência ----------

    def test_hash_confere_e_detecta_adulteracao(self):
        bruto = util.RAIZ / "fixtures" / "exemplo" / "bruto"
        ok = self.perfil("municipio", BRUTO=str(bruto))
        self.assertTrue(ok.conferir_evidencia("g1")["hash_confere"])

        adulterada = Path(self.pasta.name) / "bruto"
        shutil.copytree(bruto, adulterada)
        arquivo = adulterada / "exemplo.html"
        arquivo.write_text(arquivo.read_text(encoding="utf-8").replace("120.000,00", "999.999,00"), encoding="utf-8", newline="\n")
        ruim = self.perfil("municipio", BRUTO=str(adulterada))
        self.assertFalse(ruim.conferir_evidencia("g1")["hash_confere"])

        sumiu = self.perfil("municipio", BRUTO=str(Path(self.pasta.name) / "nao-existe"))
        self.assertFalse(sumiu.conferir_evidencia("g1")["hash_confere"])

    # ---------- Registro ----------

    def test_o_registro_diz_quem_perguntou_o_que_e_quais_fontes(self):
        m = self.perfil("estado", TRANSPARENCIA_SESSAO="pergunta-42")
        m.sancoes_do_fornecedor(A)
        m.conferir_evidencia("x1")                       # negada
        reg = [json.loads(l) for l in self.log.read_text(encoding="utf-8").splitlines()]
        self.assertEqual([r["tool"] for r in reg], ["sancoes_do_fornecedor", "conferir_evidencia"])
        self.assertTrue(all(r["perfil"] == "estado" and r["sessao"] == "pergunta-42" for r in reg))
        self.assertEqual(reg[0]["evidencias"], ["e1"])
        self.assertEqual((reg[1]["resultados"], reg[1]["evidencias"]), (0, []))


if __name__ == "__main__":
    unittest.main()
