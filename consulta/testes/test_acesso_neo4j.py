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
D = "cnpj:44444444000144"      # Federal Exemplo: só existe na União (sanção CNEP, cadastro da Receita e um contrato federal); nenhum contrato de Estado ou município
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

    # ---------- União (CEIS e CNEP): só o perfil que a inclui enxerga; os outros ficam como estavam ----------

    def test_perfis_sem_a_uniao_nao_enxergam_nada_federal(self):
        for nome in ("municipio", "estado", "estado-exemplo"):
            m = self.perfil(nome)
            self.assertEqual(m.sancoes_do_fornecedor(D), [], nome)
            self.assertEqual(m.buscar_fornecedor("Federal Exemplo"), [], nome)
            self.assertEqual(m.buscar_fornecedor("44444444000144"), [], nome)
            for negada in ("u1", "u2"):
                self.assertIn("erro", m.conferir_evidencia(negada), (nome, negada))
            self.assertNotIn("br-uniao", [s["ente"] for s in m.sancoes_do_fornecedor(A)], nome)
            self.assertNotIn("br-uniao", m.cobertura()["tenants_do_perfil"], nome)

    def test_estado_e_uniao_ve_as_sancoes_federais_com_data_e_abrangencia(self):
        u = self.perfil("estado-uniao")
        por_ente = {s["ente"]: s for s in u.sancoes_do_fornecedor(A)}
        self.assertEqual(set(por_ente), {"pe-estado", "br-uniao"})
        federal = por_ente["br-uniao"]
        self.assertEqual((federal["cadastro"], federal["inicio_suspensao"], federal["fim_suspensao"], federal["publicada_em"], federal.get("valor_multa")),
                         ("CEIS", "2026-03-01", "2028-03-01", "2026-03-05", None))
        self.assertEqual((federal["abrangencia"], federal["situacao"]), ("Todas as Esferas em todos os Poderes", None))
        for campo in ("cadastro", "inicio_suspensao", "abrangencia", "valor_multa"):
            self.assertNotIn(campo, por_ente["pe-estado"], campo)                      # a estadual não ganhou campo que não tem (nem como nulo)
        self.assertNotIn("valor_multa", federal)                                       # o CEIS não tem multa

    def test_empresa_so_da_uniao_aparece_na_busca_sem_contrato_de_estado_ou_municipio(self):
        u = self.perfil("estado-uniao")
        self.assertEqual([f["id"] for f in u.buscar_fornecedor("Federal Exemplo")], [D])
        self.assertEqual([f["id"] for f in u.buscar_fornecedor("44444444000144")], [D])         # CNPJ exato
        self.assertEqual([f["id"] for f in u.buscar_fornecedor("federal exemlo")], [D])         # erro de digitação
        self.assertEqual({c["ente"] for c in u.contratos_do_fornecedor(D)}, {"br-uniao"})          # os contratos dela são todos federais
        (s,) = u.sancoes_do_fornecedor(D)
        self.assertEqual((s["cadastro"], s["tipo"], s["valor_multa"], s["ente"]), ("CNEP", "Multa", 25000.5, "br-uniao"))

    def test_estado_e_uniao_abre_a_prova_da_federal_com_o_hash_conferido(self):
        u = self.perfil("estado-uniao", BRUTO="fixtures/exemplo/bruto")
        for ident in ("u1", "u2"):
            r = u.conferir_evidencia(ident)
            self.assertNotIn("erro", r, ident)
            self.assertTrue(r["hash_confere"], ident)
            self.assertIn("DADO FICTÍCIO", r["trecho"])
        self.assertIn("abrangência", u.conferir_evidencia("u1")["trecho"])

    def test_a_uniao_nao_abre_o_acesso_a_outro_estado_nem_a_pessoa_fisica(self):
        u = self.perfil("estado-uniao")
        for negada in ("x1", "x2", "g4"):
            self.assertIn("erro", u.conferir_evidencia(negada), negada)
        self.assertEqual(u.buscar_fornecedor("Obras Exemplares"), [])
        self.assertEqual(u.contratos_do_fornecedor(PF), [])
        self.assertNotIn("ex-estado", [s["ente"] for s in u.sancoes_do_fornecedor(A)])

    def test_a_cobertura_conta_as_sancoes_da_uniao_no_perfil_que_as_inclui(self):
        self.assertEqual(self.perfil("estado").cobertura()["sancoes"], 1)
        self.assertEqual(self.perfil("estado-uniao").cobertura()["sancoes"], 3)       # a de PE e as duas federais

    def test_o_nome_dos_contratos_nao_e_trocado_pela_razao_social_da_receita(self):
        """O nome já gravado fica; o do CEIS/CNEP só preenche quando não havia nenhum."""
        u = self.perfil("estado-uniao")
        (a,) = [f for f in u.buscar_fornecedor("Construtora") if f["id"] == A]
        self.assertEqual(a["nome"], "Construtora Exemplo Ltda (fictícia)")

    # ---------- Cadastro de CNPJ da Receita: mesmo isolamento da União ----------

    def test_a_cobertura_diz_de_quando_e_cada_cadastro_de_sancoes_e_a_data_de_pe_so_vale_para_pe(self):
        cob = self.perfil("estado").cobertura()
        self.assertEqual([(x["ente"], x["sancoes"]) for x in cob["sancoes_por_ente"]], [("Estado de Pernambuco", 1)])
        self.assertEqual(cob["cadastro_de_sancoes_de"], "2025-06-05")
        uniao = self.perfil("estado-uniao").cobertura()
        self.assertEqual({x["ente"]: x["sancoes"] for x in uniao["sancoes_por_ente"]}, {"Estado de Pernambuco": 1, "União (governo federal)": 2})
        self.assertTrue(all(x["coletado_de"] and x["coletado_ate"] for x in uniao["sancoes_por_ente"]))
        # um perfil sem sanção de Pernambuco não pode receber a data de Pernambuco
        sem_pe = self.perfil("estado-exemplo").cobertura()
        self.assertNotIn("Estado de Pernambuco", [x["ente"] for x in sem_pe["sancoes_por_ente"]])

    def test_cadastro_da_receita_so_aparece_para_quem_enxerga_a_uniao(self):
        for nome in ("municipio", "estado", "estado-exemplo"):
            m = self.perfil(nome)
            self.assertEqual(m.cadastro_do_fornecedor(D), [], nome)
            self.assertIn("erro", m.conferir_evidencia("u3"), nome)
            self.assertEqual(m.cobertura()["cadastros_da_receita"], 0, nome)

    def test_estado_e_uniao_le_o_cadastro_com_a_data_da_coleta_e_a_fonte(self):
        u = self.perfil("estado-uniao")
        (c,) = u.cadastro_do_fornecedor(D)
        self.assertEqual((c["razao_social"], c["situacao"], c["situacao_desde"], c["cnae"], c["porte"], c["matriz_filial"], c["capital_social"]),
                         ("FEDERAL EXEMPLO S.A. (FICTÍCIA)", "ATIVA", "2010-02-01", "0000000", "DEMAIS", "MATRIZ", 77000.0))
        self.assertEqual((c["ente"], c["evidencia"], c["coletado_em"]), ("br-uniao", "u3", "2026-11-05"))
        self.assertIn("BrasilAPI", c["fonte"])
        self.assertEqual(u.cobertura()["cadastros_da_receita"], 1)

    def test_a_marca_do_nome_fantasia_acha_a_empresa_e_nao_atravessa_o_isolamento(self):
        u = self.perfil("estado-uniao")
        (f,) = u.buscar_fornecedor("marca exemplar")
        self.assertEqual((f["id"], f["nome_fantasia"]), (D, "Marca Exemplar"))
        self.assertEqual([x["id"] for x in u.buscar_fornecedor("marca exemplr")], [D])           # erro de digitação
        for nome in ("municipio", "estado", "estado-exemplo"):
            self.assertEqual(self.perfil(nome).buscar_fornecedor("marca exemplar"), [], nome)

    def test_fornecedor_sem_cadastro_coletado_devolve_lista_vazia(self):
        u = self.perfil("estado-uniao")
        self.assertEqual(u.cadastro_do_fornecedor(A), [])                  # tem contrato e sanção, mas ninguém coletou o cadastro
        self.assertEqual(u.cadastro_do_fornecedor(PF), [])

    def test_cadastro_do_fornecedor_rejeita_id_estranho(self):
        u = self.perfil("estado-uniao")
        for ruim in ("", "x" * 200, "cnpj:1 OR 1=1", "cnpj:11'; MATCH (n) DETACH DELETE n //"):
            with self.assertRaises(ValueError):
                u.cadastro_do_fornecedor(ruim)

    def test_prova_do_cadastro_confere_o_hash_e_traz_a_situacao(self):
        u = self.perfil("estado-uniao", BRUTO="fixtures/exemplo/bruto")
        r = u.conferir_evidencia("u3")
        self.assertNotIn("erro", r)
        self.assertTrue(r["hash_confere"])
        self.assertIn("situação ATIVA desde 01/02/2010", r["trecho"])

    # ---------- Contratos federais: mesmo isolamento da União, e os dois valores separados ----------

    def test_contrato_federal_so_aparece_para_quem_enxerga_a_uniao(self):
        for nome in ("municipio", "estado", "estado-exemplo"):
            m = self.perfil(nome)
            self.assertEqual(m.contratos_do_fornecedor(D), [], nome)
            self.assertNotIn("9/2026", [c["numero"] for c in m.listar_contratos()], nome)
            self.assertIn("erro", m.conferir_evidencia("u4"), nome)
            self.assertNotIn("União (governo federal)", [x["ente"] for x in m.cobertura()["contratos_por_ente"]], nome)

    def test_estado_e_uniao_ve_o_contrato_federal_com_valor_inicial_e_final_separados(self):
        u = self.perfil("estado-uniao", BRUTO="fixtures/exemplo/bruto")
        (c,) = [x for x in u.contratos_do_fornecedor(D) if x["numero"] == "9/2026"]
        self.assertEqual((c["numero"], c["valor_contratado"], c["valor_final"], c["situacao"], c["orgao_superior"], c["ente"], c["evidencia"]),
                         ("9/2026", 61000.0, 63000.0, "Em execução", "MEX", "br-uniao", "u4"))
        self.assertEqual((c["modalidade"], c["fonte"]), ("Pregão", "Portal da Transparência (federal)"))
        self.assertIsNone(c["tem_aditivo"])
        self.assertIn("9/2026", [x["numero"] for x in u.listar_contratos()])
        self.assertIn("União (governo federal)", [x["ente"] for x in u.cobertura()["contratos_por_ente"]])
        r = u.conferir_evidencia("u4")
        self.assertTrue(r["hash_confere"])
        self.assertIn("valor final R$ 63.000,00", r["trecho"])

    def test_contrato_sem_valor_vai_para_o_fim_da_lista_dos_maiores(self):
        """Valor nulo ordena como o maior no Cypher: sem tratamento, o contrato sem valor (comum no PNCP) abriria a lista `do maior para o menor`."""
        u = self.perfil("estado-uniao")
        lista = u.listar_contratos()
        valores = [c["valor_contratado"] for c in lista]
        self.assertEqual(lista[-1]["numero"], "10/2026")                                 # o sem valor vai para o fim
        com_valor = [v for v in valores if v is not None]
        self.assertEqual(com_valor, sorted(com_valor, reverse=True))                      # e os demais seguem do maior para o menor
        self.assertEqual(valores.count(None), 1)
        self.assertEqual([c["numero"] for c in u.buscar_contratos("fictício sem valor")], ["10/2026"])

    def test_contrato_antigo_continua_com_os_campos_novos_nulos(self):
        u = self.perfil("estado-uniao")
        contratos = u.contratos_do_fornecedor(B)
        self.assertTrue(contratos)
        for c in contratos:
            for campo in ("valor_final", "situacao", "orgao_superior", "fonte"):
                self.assertNotIn(campo, c, campo)                                      # nem como nulo: o modelo comentaria o que a fonte nem tem

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
