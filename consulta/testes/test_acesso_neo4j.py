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

    # ---------- Busca por texto (índice de texto, passo 4): tolera acento e erro, e não amplia o acesso ----------

    def test_busca_ignora_acento_tolera_erro_de_digitacao_e_ordem(self):
        m = self.perfil("municipio")
        for texto in ("Serviços Modelo", "servicos modelo", "SERVICOS MODELO", "Servicos Modelos", "Serviçoz Modelo", "Modelo Servicos", "Serv", "modelo"):
            self.assertEqual([f["id"] for f in m.buscar_fornecedor(texto)], [B], texto)
        self.assertEqual([f["id"] for f in m.buscar_fornecedor("Construtra")], [A])          # uma letra a menos
        self.assertEqual(m.buscar_fornecedor("Servicos Exemplo"), [])                        # palavras de duas empresas não formam uma terceira

    def test_busca_difusa_nao_atravessa_o_isolamento(self):
        # o erro de digitação e o começo de palavra não podem trazer empresa de outro ente
        m = self.perfil("municipio")
        for texto in ("Obras Exemplares", "obras exemplars", "Exemplares", "Obras", "Obra Exemplar", "33333333000133"):
            self.assertEqual(m.buscar_fornecedor(texto), [], texto)
        x = self.perfil("estado-exemplo")
        for texto in ("Serviços Modelo", "servicos modelo", "Servicos Modelos"):
            self.assertEqual(x.buscar_fornecedor(texto), [], texto)
        self.assertEqual([f["id"] for f in x.buscar_fornecedor("obras exemplars")], [C])

    def test_busca_sem_palavra_util_devolve_vazio_e_nao_tudo(self):
        m = self.perfil("municipio")
        for texto in ("!!!", "* ?", "a", "-"):
            self.assertEqual(m.buscar_contratos(texto), [], texto)
            self.assertEqual(m.buscar_fornecedor(texto), [], texto)

    def test_busca_por_cnpj_continua_exata(self):
        m = self.perfil("municipio")
        self.assertEqual([f["id"] for f in m.buscar_fornecedor("11.111.111/0001-11")], [A])
        self.assertEqual(m.buscar_fornecedor("11111111000112"), [])       # um dígito errado não casa

    def test_busca_de_contrato_ignora_acento_e_tem_o_mesmo_isolamento(self):
        m = self.perfil("municipio")
        for texto in ("reforma", "Reformas", "REFORMA DE ESCOLA", "escola reforma", "reformas de escolas"):
            self.assertEqual([c["numero"] for c in m.buscar_contratos(texto)], ["1/2026"], texto)
        for texto in ("pavimentacao", "pavimentação", "pavimentcao", "consultoria"):         # outro estado e pessoa física
            self.assertEqual(m.buscar_contratos(texto), [], texto)
        x = self.perfil("estado-exemplo")
        self.assertEqual([c["numero"] for c in x.buscar_contratos("pavimentacao")], ["1/2026"])
        self.assertEqual(x.buscar_contratos("reforma"), [])

    def test_busca_de_contrato_acha_pelo_nome_do_orgao_sem_acento(self):
        m = self.perfil("municipio")
        self.assertTrue(m.buscar_contratos("secretaria de exemplo"))
        self.assertTrue(all(c["unidade"] == "SECRETARIA DE EXEMPLO" for c in m.buscar_contratos("SECRETARIA exemplo")))

    def test_sintaxe_do_indice_digitada_pelo_usuario_nao_quebra_nem_amplia(self):
        m = self.perfil("municipio")
        for texto in ('x" OR 1=1', "*:*", "nome:*", "Construtora~", "((((", "AND OR NOT", "\\", "-Construtora +Obras", "/.*/", "*", "?"):
            for busca in (m.buscar_fornecedor, m.buscar_contratos):
                resultado = busca(texto)
                self.assertTrue(set(r.get("id") or r["fornecedor_id"] for r in resultado) <= {A, B}, (busca.__name__, texto, resultado))

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

    # ---------- Consultas de contrato por termo e de execução financeira ----------

    def test_busca_de_contratos_respeita_ente_e_dado_pessoal(self):
        m = self.perfil("municipio")
        self.assertEqual([c["numero"] for c in m.buscar_contratos("reforma")], ["1/2026"])
        self.assertEqual(m.buscar_contratos("consultoria"), [])      # só existe em contrato de pessoa física
        self.assertEqual(m.buscar_contratos("pavimentação"), [])     # só existe em outro estado
        x = self.perfil("estado-exemplo")
        self.assertEqual([c["numero"] for c in x.buscar_contratos("pavimentação")], ["1/2026"])
        self.assertEqual(x.buscar_contratos("reforma"), [])

    def test_execucao_so_do_ente_do_perfil(self):
        self.assertEqual(self.perfil("municipio").execucao_do_fornecedor(A), [])
        self.assertEqual([x["pago"] for x in self.perfil("estado").execucao_do_fornecedor(A)], [7000.0])
        self.assertEqual([x["pago"] for x in self.perfil("estado-exemplo").execucao_do_fornecedor(A)], [9000.0])

    def test_evidencia_da_execucao_nao_cruza_estados(self):
        e = self.perfil("estado")
        self.assertIn("erro", e.conferir_evidencia("x3"))
        self.assertNotIn("erro", e.conferir_evidencia("e2"))

    def test_cobertura_so_lista_orgaos_do_perfil(self):
        nomes = [o["orgao"] for o in self.perfil("municipio").cobertura()["orgaos"]]
        self.assertEqual(nomes, ["SECRETARIA DE EXEMPLO"])

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

    def test_bruto_relativo_vale_a_partir_da_raiz_do_projeto(self):
        # O agente roda o servidor em outra pasta. Um BRUTO relativo no .env não pode depender do diretório atual.
        antes = os.getcwd()
        os.chdir(self.pasta.name)
        try:
            relativo = self.perfil("municipio", BRUTO="fixtures/exemplo/bruto")
            self.assertTrue(relativo.conferir_evidencia("g1")["hash_confere"])
        finally:
            os.chdir(antes)

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
