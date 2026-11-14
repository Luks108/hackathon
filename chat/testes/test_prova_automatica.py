"""Passo 3: a conferência em tempo de execução. Quando o modelo cita um fato e não abre a prova, o código a abre.
Sem internet e sem gastar token: o agente é falso e, para o banco, há um teste que só roda com o Neo4j de exemplo no ar.

    python -m unittest discover -s chat/testes -v
"""
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import agente  # noqa: E402
import provedores  # noqa: E402

TENANTS = ["pe-estado", "pe-garanhuns"]
CONTRATO = {"numero": "3/2026", "valor_contratado": 415926.25, "fornecedor": "Araçá Engenharia Ltda (fictícia)",
            "unidade": "SECRETARIA DE SAÚDE", "evidencia": "c1"}
OUTRO = {"numero": "9/2025", "valor_contratado": 80000.0, "fornecedor": "Bromélia Serviços Ltda", "unidade": "SECRETARIA DE CULTURA",
         "evidencia": "c9"}
ABERTA = {"trecho": "Contrato 3/2026 | R$ 415.926,25", "url": "https://exemplo.invalid/f", "arquivo": "x/benchmark.html",
          "documento_hash": "a" * 64, "tabela": "benchmark", "linha": 1, "capturado_em": "2026-11-05", "trecho_mascarado": False,
          "hash_confere": True}


def leitor_com(fatos, resposta, abertas=()):
    leitor = agente.Leitor()
    leitor.fatos, leitor.resposta, leitor.evidencias = list(fatos), resposta, list(abertas)
    leitor.request_id = "teste"
    return leitor


def resultado_de_tool(nome, itens, id_="t1"):
    """Os dois eventos do stream-json: o modelo chama a tool e o resultado volta."""
    return [{"type": "assistant", "message": {"content": [{"type": "tool_use", "id": id_, "name": agente.PREFIXO + nome, "input": {}}]}},
            {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": id_,
                                                       "content": [{"type": "text", "text": json.dumps(itens)}]}]}}]


class TestLeitorGuardaOsFatos(unittest.TestCase):
    def ler(self, leitor, eventos):
        return [e for bruto in eventos for e in leitor.ler(bruto)]

    def test_guarda_so_itens_que_trazem_evidencia(self):
        leitor = agente.Leitor()
        self.ler(leitor, resultado_de_tool("listar_contratos", [CONTRATO, {"numero": "5/2026", "evidencia": None}, {"nome": "x"}]))
        self.assertEqual(leitor.fatos, [CONTRATO])

    def test_resultado_de_cobertura_nao_vira_fato(self):
        leitor = agente.Leitor()
        self.ler(leitor, resultado_de_tool("cobertura", {"contratos": 120, "sancoes": 3}))
        self.assertEqual(leitor.fatos, [])

    def test_o_que_o_modelo_abriu_vai_para_as_fontes_e_nao_para_os_fatos(self):
        leitor = agente.Leitor()
        eventos = self.ler(leitor, resultado_de_tool("conferir_evidencia", ABERTA))
        self.assertEqual((leitor.fatos, [t for t, _ in eventos if t == "fonte"]), ([], ["fonte"]))

    def test_tool_de_fora_do_servidor_nao_conta(self):
        leitor = agente.Leitor()
        bruto = resultado_de_tool("x", [CONTRATO])
        bruto[0]["message"]["content"][0]["name"] = "Bash"
        self.ler(leitor, bruto)
        self.assertEqual(leitor.fatos, [])

    def test_ha_um_teto_de_fatos_guardados(self):
        leitor = agente.Leitor()
        itens = [{**CONTRATO, "evidencia": f"c{i}"} for i in range(agente.MAX_FATOS + 50)]
        self.ler(leitor, resultado_de_tool("listar_contratos", itens))
        self.assertEqual(len(leitor.fatos), agente.MAX_FATOS)

    def test_zerar_descarta_os_fatos_da_tentativa_anterior(self):
        leitor = agente.Leitor()
        self.ler(leitor, resultado_de_tool("listar_contratos", [CONTRATO]))
        leitor.zerar()
        self.assertEqual(leitor.fatos, [])


class TestRegistrarFonte(unittest.TestCase):
    def test_automatica_e_marcada_e_o_resto_e_igual(self):
        a = agente.Leitor().registrar_fonte("c1", dict(ABERTA))
        b = agente.Leitor().registrar_fonte("c1", dict(ABERTA), automatica=True)
        self.assertNotIn("automatica", a[1])
        self.assertTrue(b[1].pop("automatica"))
        self.assertEqual(a, b)
        self.assertEqual(a[1]["arquivo"], "benchmark.html")        # só o nome, nunca o caminho

    def test_nao_repete_nem_aceita_sem_trecho(self):
        leitor = agente.Leitor()
        self.assertIsNotNone(leitor.registrar_fonte("c1", dict(ABERTA)))
        self.assertIsNone(leitor.registrar_fonte("c1", dict(ABERTA)))
        self.assertIsNone(leitor.registrar_fonte("c2", {"trecho": ""}))
        self.assertEqual(leitor.evidencias, ["c1"])

    def test_cpf_continua_mascarado_na_prova_automatica(self):
        evento = agente.Leitor().registrar_fonte("c1", {**ABERTA, "trecho": "Titular 123.456.789-09 recebeu"}, automatica=True)
        self.assertNotIn("123.456.789-09", evento[1]["trecho"])

    def test_evidencia_negada_vira_alerta_e_nao_fonte(self):
        leitor = agente.Leitor()
        self.assertIsNone(leitor.registrar_fonte("e1", {"erro": "evidência não encontrada para este perfil"}, automatica=True))
        self.assertEqual([a[0] for a in leitor.alertas], ["evidencia_negada"])


class TestCompletarProvas(unittest.TestCase):
    def rodar(self, leitor, abrir=None, ligada=True):
        abrir = abrir or mock.Mock(return_value=dict(ABERTA))
        with mock.patch.object(agente, "abrir_prova", abrir), mock.patch.object(agente, "PROVA_AUTOMATICA", ligada), \
                mock.patch.object(agente, "_log") as log:
            eventos = list(agente.completar_provas(leitor, TENANTS))
        return eventos, abrir, log

    def test_abre_a_prova_do_fato_que_a_resposta_cita(self):
        leitor = leitor_com([CONTRATO, OUTRO], "O contrato 3/2026 vale R$ 415.926,25.")
        eventos, abrir, _ = self.rodar(leitor)
        abrir.assert_called_once_with(TENANTS, "c1")
        (tipo, dados), = eventos
        self.assertEqual((tipo, dados["evidencia"], dados["automatica"], dados["hash_confere"]), ("fonte", "c1", True, True))
        self.assertEqual(leitor.evidencias, ["c1"])

    def test_nao_abre_o_que_o_modelo_ja_abriu(self):
        leitor = leitor_com([CONTRATO], "O contrato 3/2026.", abertas=["c1"])
        eventos, abrir, _ = self.rodar(leitor)
        self.assertEqual(eventos, [])
        abrir.assert_not_called()

    def test_completa_ate_tres_no_total(self):
        fatos = [{**CONTRATO, "numero": f"{i}/2026", "evidencia": f"c{i}"} for i in range(1, 7)]
        leitor = leitor_com(fatos, " ".join(f"{i}/2026" for i in range(1, 7)), abertas=["x1"])
        eventos, abrir, _ = self.rodar(leitor, abrir=mock.Mock(side_effect=lambda t, i: {**ABERTA, "trecho": f"trecho {i}"}))
        self.assertEqual([e[1]["evidencia"] for e in eventos], ["c1", "c2"])
        self.assertEqual(len(leitor.evidencias), 3)

    def test_resposta_que_nao_cita_fato_nenhum_nao_ganha_prova(self):
        leitor = leitor_com([CONTRATO, OUTRO], "A base tem 120 contratos.")
        eventos, abrir, _ = self.rodar(leitor)
        self.assertEqual(eventos, [])
        abrir.assert_not_called()

    def test_recusa_que_so_cita_o_nome_nao_ganha_prova(self):
        # visto no subconjunto real: uma recusa que dizia o CNPJ e o órgão recebeu a prova de um contrato que ninguém citou
        leitor = leitor_com([CONTRATO, OUTRO], "Não consigo listar contratos da Bromélia Serviços na SECRETARIA DE SAÚDE.")
        eventos, abrir, _ = self.rodar(leitor)
        self.assertEqual(eventos, [])
        abrir.assert_not_called()

    def test_contagem_do_orgao_nao_ganha_prova_de_contratos_soltos(self):
        leitor = leitor_com([CONTRATO, OUTRO], "**12** contratos na SECRETARIA DE CULTURA, da Bromélia Serviços e de outras.")
        eventos, abrir, _ = self.rodar(leitor)
        self.assertEqual(eventos, [])
        abrir.assert_not_called()

    def test_sem_fatos_nao_faz_nada_nem_alerta(self):
        eventos, abrir, log = self.rodar(leitor_com([], "O contrato 3/2026 vale R$ 415.926,25."))
        self.assertEqual(eventos, [])
        abrir.assert_not_called()
        log.assert_not_called()

    def test_falha_ao_abrir_nao_derruba_a_resposta(self):
        leitor = leitor_com([CONTRATO], "O contrato 3/2026.")
        eventos, _, log = self.rodar(leitor, abrir=mock.Mock(side_effect=ConnectionError("neo4j fora")))
        self.assertEqual(eventos, [])
        self.assertEqual(leitor.evidencias, [])
        self.assertIn("prova_automatica_falhou", [c.args[1] for c in log.call_args_list])

    def test_banco_parado_para_de_tentar_as_demais_mas_id_recusado_nao(self):
        fatos = [{**CONTRATO, "numero": f"{i}/2026", "evidencia": f"c{i}"} for i in range(1, 4)]
        resposta = "Contratos 1/2026, 2/2026 e 3/2026."
        eventos, abrir, _ = self.rodar(leitor_com(fatos, resposta), abrir=mock.Mock(side_effect=ConnectionError("neo4j fora")))
        self.assertEqual((eventos, abrir.call_count), ([], 1))             # o banco não responde: uma tentativa só, não três esperas
        recusa = mock.Mock(side_effect=[ValueError("evidencia_id inválido"), dict(ABERTA), dict(ABERTA)])
        eventos, abrir, _ = self.rodar(leitor_com(fatos, resposta), abrir=recusa)
        self.assertEqual((len(eventos), abrir.call_count), (2, 3))         # uma evidência recusada não impede as outras

    def test_evidencia_negada_nao_vira_fonte(self):
        leitor = leitor_com([CONTRATO], "O contrato 3/2026.")
        eventos, _, _ = self.rodar(leitor, abrir=mock.Mock(return_value={"erro": "evidência não encontrada para este perfil"}))
        self.assertEqual(eventos, [])
        self.assertEqual([a[0] for a in leitor.alertas], ["evidencia_negada"])

    def test_desligada_por_variavel_de_ambiente(self):
        leitor = leitor_com([CONTRATO], "O contrato 3/2026.")
        eventos, abrir, _ = self.rodar(leitor, ligada=False)
        self.assertEqual(eventos, [])
        abrir.assert_not_called()

    def test_resposta_com_valor_e_sem_prova_fica_registrada(self):
        # as tools devolveram evidências, a resposta cita um valor, mas nenhum fato bate com o texto
        leitor = leitor_com([OUTRO], "O contrato custou R$ 999.999,00.")
        eventos, _, log = self.rodar(leitor)
        self.assertEqual(eventos, [])
        chamadas = [c for c in log.call_args_list if c.args[1] == "resposta_sem_prova"]
        self.assertEqual(len(chamadas), 1)
        self.assertEqual(chamadas[0].kwargs["fatos_com_evidencia"], 1)

    def test_resposta_provada_nao_gera_o_registro_de_sem_prova(self):
        _, _, log = self.rodar(leitor_com([CONTRATO], "O contrato 3/2026."))
        self.assertNotIn("resposta_sem_prova", [c.args[1] for c in log.call_args_list])

    def test_resposta_sem_valor_nem_contrato_nao_e_sem_prova(self):
        _, _, log = self.rodar(leitor_com([OUTRO], "Há contratos na área de cultura."))
        self.assertNotIn("resposta_sem_prova", [c.args[1] for c in log.call_args_list])


class TestConexaoComOGrafo(unittest.TestCase):
    def setUp(self):
        self.addCleanup(setattr, agente, "_DRIVER", agente._DRIVER)
        agente._DRIVER = None

    def test_varias_threads_criam_uma_conexao_so_e_com_limite_de_tempo(self):
        import threading
        import time
        import neo4j
        criados = []

        def criar(*a, **kw):
            time.sleep(0.05)          # criar a conexão demora: sem a trava, as outras threads passam pelo `if` enquanto isso
            criados.append(kw)
            return mock.Mock()

        with mock.patch.object(neo4j.GraphDatabase, "driver", side_effect=criar), mock.patch.object(agente.atexit, "register"):
            ts = [threading.Thread(target=agente._executar_no_grafo, args=(["pe-estado"], ["publico"])) for _ in range(16)]
            [t.start() for t in ts]
            [t.join() for t in ts]
        self.assertEqual(len(criados), 1)
        self.assertEqual(criados[0]["connection_timeout"], agente.TEMPO_DA_PROVA_S)
        self.assertEqual(criados[0]["connection_acquisition_timeout"], agente.TEMPO_DA_PROVA_S)

    def test_a_consulta_leva_limite_de_tempo_e_os_entes_do_perfil(self):
        import neo4j
        sessao = mock.MagicMock()
        sessao.__enter__.return_value.run.return_value = iter([{"trecho": "t"}])
        agente._DRIVER = mock.Mock(session=mock.Mock(return_value=sessao))
        linhas = agente._executar_no_grafo(["pe-garanhuns"], ["publico"])("MATCH (n) RETURN n", id="g1")
        consulta, = sessao.__enter__.return_value.run.call_args.args
        self.assertIsInstance(consulta, neo4j.Query)
        self.assertEqual(consulta.timeout, agente.TEMPO_DA_PROVA_S)
        self.assertEqual(sessao.__enter__.return_value.run.call_args.kwargs, {"tenants": ["pe-garanhuns"], "sensibilidades": ["publico"], "id": "g1"})
        self.assertEqual(linhas, [{"trecho": "t"}])


class Falso:
    def __init__(self, fatos, texto, falha_antes=False):
        self.fatos, self.texto, self.falha_antes, self.chamado = fatos, texto, falha_antes, 0

    def perguntar(self, texto, tenants, historico, leitor, limite_s=None):
        self.chamado += 1
        if self.falha_antes and self.chamado == 1:
            yield "erro", {"motivo": "limite de uso do provedor atingido"}
            return
        leitor.zerar()
        leitor.fatos += self.fatos
        leitor.resposta += self.texto
        yield "texto", {"delta": self.texto}
        yield "fim", {"duracao_ms": 5}


class TestNoFluxoDoAgente(unittest.TestCase):
    def rodar(self, clientes, abrir=None):
        abrir = abrir or mock.Mock(return_value=dict(ABERTA))
        leitor = agente.Leitor()
        with mock.patch.object(provedores, "escolher", side_effect=lambda m: clientes[m]), \
                mock.patch.object(provedores, "cadeia", side_effect=lambda m: list(clientes)), \
                mock.patch.object(agente, "abrir_prova", abrir), mock.patch.object(agente, "PROVA_AUTOMATICA", True), \
                mock.patch.object(agente, "_log") as log:
            eventos = list(agente.perguntar("pergunta", TENANTS, leitor=leitor, modelo=next(iter(clientes))))
        return eventos, leitor, log, abrir

    def test_a_fonte_vem_antes_do_fim_e_entra_na_contagem_do_resumo(self):
        eventos, leitor, log, _ = self.rodar({"a": Falso([CONTRATO], "O contrato 3/2026 está ativo.")})
        self.assertEqual([t for t, _ in eventos], ["texto", "fonte", "fim"])
        resumo = next(c for c in log.call_args_list if c.args[1] == "resumo")
        self.assertEqual(resumo.kwargs["fontes"], 1)
        self.assertEqual(leitor.evidencias, ["c1"])

    def test_resposta_sem_fato_citado_continua_sem_fonte(self):
        eventos, _, _, abrir = self.rodar({"a": Falso([CONTRATO], "A base é uma amostra.")})
        self.assertEqual([t for t, _ in eventos], ["texto", "fim"])
        abrir.assert_not_called()

    def test_com_troca_de_provedor_so_vale_o_que_o_substituto_respondeu(self):
        clientes = {"a": Falso([OUTRO], "", falha_antes=True), "b": Falso([CONTRATO], "O contrato 3/2026.")}
        eventos, leitor, _, abrir = self.rodar(clientes)
        self.assertEqual([t for t, _ in eventos], ["fallback", "texto", "fonte", "fim"])
        abrir.assert_called_once_with(TENANTS, "c1")


def _grafo_de_exemplo():
    """Motivo de não poder testar contra o Neo4j de exemplo, ou None."""
    try:
        linhas = agente._executar_no_grafo(["pe-garanhuns"], ["publico"])("MATCH (e:Evidencia {id: 'g1'}) RETURN count(e) AS n")
        return None if linhas[0]["n"] else "Neo4j no ar, mas sem os dados de exemplo (python coleta/carregar_neo4j.py --zerar --exemplo)"
    except Exception as erro:  # noqa: BLE001
        return f"Neo4j indisponível ({type(erro).__name__})"
    finally:
        if agente._DRIVER is not None:
            agente._DRIVER.close()
            agente._DRIVER = None


MOTIVO = _grafo_de_exemplo()


@unittest.skipIf(MOTIVO, MOTIVO or "")
class TestAbrirProvaNoGrafoDeVerdade(unittest.TestCase):
    """O código abre a prova pelo MESMO filtro de entes e sensibilidade da tool: nunca mais do que o perfil pode ver."""

    @classmethod
    def tearDownClass(cls):
        if agente._DRIVER is not None:         # não deixa a conexão aberta depois dos testes
            agente._DRIVER.close()
            agente._DRIVER = None

    def abrir(self, tenants, ident):
        return agente.abrir_prova(tenants, ident)

    def test_municipio_abre_a_propria_e_nao_a_de_outro_ente(self):
        r = self.abrir(["pe-garanhuns"], "g1")
        self.assertNotIn("erro", r)
        self.assertTrue(r["hash_confere"])
        for negada in ("e1", "x1", "x2", "g4"):         # Estado, outro estado, pessoa física
            self.assertIn("erro", self.abrir(["pe-garanhuns"], negada), negada)

    def test_outro_estado_nao_abre_a_prova_de_pernambuco(self):
        self.assertNotIn("erro", self.abrir(["ex-estado"], "x1"))
        for negada in ("g1", "e1"):
            self.assertIn("erro", self.abrir(["ex-estado"], negada), negada)

    def test_perfil_inexistente_e_recusado_e_id_ruim_nao_chega_ao_banco(self):
        with self.assertRaises(ValueError):
            self.abrir(["ente-que-nao-existe"], "g1")
        with self.assertRaises(ValueError):
            self.abrir(["pe-garanhuns"], "g1' OR 1=1 //")


if __name__ == "__main__":
    unittest.main()
