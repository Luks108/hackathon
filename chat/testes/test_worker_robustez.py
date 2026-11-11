"""Robustez do worker: caminhos, resposta estranha da API, eventos que não chegam e laços que não podem morrer.
Sem internet, sem banco e sem .env (a chave do worker vem do ambiente do teste).

    python -m unittest discover -s chat/testes -v
"""
import io
import os
import sys
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
with mock.patch.dict(os.environ, {"WORKER_KEY": "k" * 30}):
    import worker  # noqa: E402


class Resposta(io.BytesIO):
    def __init__(self, corpo: bytes, status: int = 200):
        super().__init__(corpo)
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class TestCaminhosDoAudio(unittest.TestCase):
    def test_transcritor_fica_dentro_do_projeto(self):
        # Antes apontava para RAIZ.parent/inferencia, que não existe: toda nota de voz falhava.
        self.assertEqual(worker.TRANSCRITOR, worker.RAIZ / "inferencia" / "transcrever.py")
        self.assertTrue(worker.TRANSCRITOR.is_file())
        self.assertEqual(worker._VENV_AUDIO, worker.RAIZ / "inferencia" / ".venv")


class TestApi(unittest.TestCase):
    def test_200_que_nao_e_json_vira_502_e_nao_levanta(self):
        with mock.patch("urllib.request.urlopen", return_value=Resposta(b"<html>erro da hospedagem</html>")):
            self.assertEqual(worker.api("POST", "/worker/proxima"), (502, None))

    def test_json_e_204_continuam_funcionando(self):
        with mock.patch("urllib.request.urlopen", return_value=Resposta(b'{"id": 7}')):
            self.assertEqual(worker.api("POST", "/worker/proxima"), (200, {"id": 7}))
        with mock.patch("urllib.request.urlopen", return_value=Resposta(b"", 204)):
            self.assertEqual(worker.api("POST", "/worker/proxima"), (204, None))

    def test_erro_http_devolve_o_codigo(self):
        erro = urllib.error.HTTPError("u", 401, "x", {}, io.BytesIO(b""))
        with mock.patch("urllib.request.urlopen", side_effect=erro):
            self.assertEqual(worker.api("GET", "/x"), (401, None))


class TestLote(unittest.TestCase):
    def setUp(self):
        self.dormir = mock.patch.object(worker.time, "sleep")
        self.dormir.start()
        self.addCleanup(self.dormir.stop)
        self.reg = mock.patch.object(worker, "registrar")
        self.reg.start()
        self.addCleanup(self.reg.stop)

    def lote_com(self, respostas):
        enviados = []

        def falso(metodo, rota, corpo=None):
            enviados.append([e["seq"] for e in corpo["eventos"]])
            r = respostas.pop(0) if respostas else (200, {})
            if isinstance(r, Exception):
                raise r
            return r

        return worker.Lote(1), enviados, mock.patch.object(worker, "api", falso)

    def test_evento_nao_entregue_fica_na_fila_e_vai_no_proximo_envio(self):
        lote, enviados, patch = self.lote_com([OSError("sem rede")] * 3)
        with patch:
            lote.adicionar("consulta", {"nome": "cobertura"})      # 3 falhas de rede
            self.assertEqual([e["seq"] for e in lote.fila], [1])   # não foi descartado
            lote.adicionar("fim", {})                              # agora a rede voltou
        self.assertEqual(lote.fila, [])
        self.assertEqual(enviados[-1], [1, 2])                    # o `fim` chegou junto com o que ficou

    def test_5xx_tambem_mantem_os_eventos(self):
        lote, _, patch = self.lote_com([(503, None)] * 3)
        with patch:
            lote.adicionar("fim", {})
        self.assertEqual(len(lote.fila), 1)

    def test_recusa_4xx_descarta_porque_repetir_nao_adianta(self):
        lote, _, patch = self.lote_com([(400, None)])
        with patch:
            lote.adicionar("fim", {})
        self.assertEqual(lote.fila, [])

    def test_409_encerra_o_lote(self):
        lote, _, patch = self.lote_com([(409, None)])
        with patch:
            lote.adicionar("consulta", {"nome": "x"})
        self.assertTrue(lote.encerrada)

    def test_texto_de_seq_que_ja_tentou_sair_nao_recebe_mais_texto(self):
        # Se o servidor gravou o seq 1 mas a resposta se perdeu, um seq repetido seria ignorado: o texto novo sumiria.
        lote, _, patch = self.lote_com([OSError("x")] * 3)
        with patch:
            lote.ultimo = worker.time.monotonic() + 100            # força o envio do texto a ficar para depois
            lote.adicionar("texto", {"delta": "Olá"})
            lote.enviar()                                          # falha: o seq 1 fica travado
            lote.adicionar("texto", {"delta": " mundo"})
        self.assertEqual([(e["seq"], e["dados"]["delta"]) for e in lote.fila], [(1, "Olá"), (2, " mundo")])

    def test_texto_ainda_nao_enviado_continua_sendo_junto(self):
        lote, enviados, patch = self.lote_com([])
        with patch:
            lote.ultimo = worker.time.monotonic() + 100
            lote.adicionar("texto", {"delta": "Olá"})
            lote.adicionar("texto", {"delta": " mundo"})
        self.assertEqual([(e["seq"], e["dados"]["delta"]) for e in lote.fila], [(1, "Olá mundo")])
        self.assertEqual(enviados, [])

    def test_fila_grande_sai_em_lotes_de_no_maximo_100(self):
        lote, enviados, patch = self.lote_com([])
        lote.fila = [{"seq": i, "tipo": "consulta", "dados": {}} for i in range(1, 251)]
        with patch:
            lote.enviar()
        self.assertEqual([len(x) for x in enviados], [100, 100, 50])
        self.assertEqual(lote.fila, [])


class TestLacosNaoMorrem(unittest.TestCase):
    def test_laco_do_site_sobrevive_a_erro_inesperado(self):
        chamadas = []

        def api(*_a, **_k):
            chamadas.append(1)
            if len(chamadas) == 1:
                raise ValueError("coisa inesperada")
            worker.parar.set()
            return 204, None

        worker.parar.clear()
        self.addCleanup(worker.parar.clear)
        with mock.patch.object(worker, "api", api), mock.patch.object(worker, "registrar"), \
                mock.patch.object(worker.parar, "wait", lambda *_: None):
            worker.laco_site()
        self.assertEqual(len(chamadas), 2)       # depois do erro, voltou a buscar

    def test_sem_pgrep_a_sessao_de_canal_conta_como_fechada(self):
        with mock.patch.object(worker.subprocess, "run", side_effect=FileNotFoundError("pgrep")):
            self.assertFalse(worker.sessao_de_canal_aberta())

    def test_pgrep_acha_a_sessao(self):
        with mock.patch.object(worker.os, "name", "posix"), \
                mock.patch.object(worker.subprocess, "run", return_value=mock.Mock(returncode=0)) as run:
            self.assertTrue(worker.sessao_de_canal_aberta())
        self.assertEqual(run.call_args.args[0][0], "pgrep")

    def test_no_windows_usa_powershell_e_exclui_o_proprio_comando(self):
        with mock.patch.object(worker.os, "name", "nt"), \
                mock.patch.object(worker.subprocess, "run", return_value=mock.Mock(returncode=0, stdout="1\n")) as run:
            self.assertTrue(worker.sessao_de_canal_aberta())
        comando = run.call_args.args[0]
        self.assertEqual(comando[0], "powershell")
        self.assertIn("$PID", comando[-1])
        with mock.patch.object(worker.os, "name", "nt"), \
                mock.patch.object(worker.subprocess, "run", return_value=mock.Mock(returncode=0, stdout="0\n")):
            self.assertFalse(worker.sessao_de_canal_aberta())


class TestPerfilPorNumero(unittest.TestCase):
    """AP-18: a sincronização dos telefones não pode abrir uma janela em que um número do site cai no perfil amplo (PERFIL_MANUAL)."""
    NUMERO = "5587991234567"
    RESTRITO = ["pe-garanhuns"]

    def setUp(self):
        self.antes = worker.perfis_por_numero
        self.addCleanup(setattr, worker, "perfis_por_numero", self.antes)
        self.estado = mock.patch.object(worker, "ESTADO", Path("/nao/existe"))     # sem access.json: a sincronização para depois do perfil
        self.estado.start()
        self.addCleanup(self.estado.stop)

    def test_numero_do_site_recebe_os_entes_do_plano_e_o_do_dono_o_perfil_manual(self):
        worker.perfis_por_numero = {worker.normalizar(self.NUMERO): self.RESTRITO}
        self.assertEqual(worker.tenants_do_numero(self.NUMERO), self.RESTRITO)
        self.assertEqual(worker.tenants_do_numero("5587900000000"), worker.PERFIL_MANUAL)

    def test_sincronizar_nunca_mostra_o_numero_sem_perfil(self):
        """Uma leitura feita no instante exato em que o dicionário é esvaziado (o que um `clear()` seguido de `update()` permite)."""
        lista = [{"numero": self.NUMERO, "tenants": self.RESTRITO}]
        vistos = []

        class Espiao(dict):
            """Faz uma leitura logo depois de cada esvaziamento ou de cada acréscimo em lote, como outra thread poderia fazer."""
            def clear(self):
                super().clear()
                vistos.append(worker.tenants_do_numero(TestPerfilPorNumero.NUMERO))

            def update(self, *a, **k):
                vistos.append(worker.tenants_do_numero(TestPerfilPorNumero.NUMERO))
                super().update(*a, **k)

        worker.perfis_por_numero = Espiao({worker.normalizar(self.NUMERO): self.RESTRITO})
        with mock.patch.object(worker, "api", return_value=(200, lista)):
            worker.sincronizar_telefones()
        self.assertEqual(worker.tenants_do_numero(self.NUMERO), self.RESTRITO)       # no fim, o perfil do plano
        self.assertNotIn(worker.PERFIL_MANUAL, vistos)                               # e em nenhum instante o número ficou sem ele

    def test_telefone_revogado_deixa_de_ter_perfil_do_site(self):
        worker.perfis_por_numero = {worker.normalizar(self.NUMERO): self.RESTRITO}
        with mock.patch.object(worker, "api", return_value=(200, [])):
            worker.sincronizar_telefones()
        self.assertEqual(worker.perfis_por_numero, {})

    def test_falha_da_api_mantem_os_perfis_anteriores(self):
        worker.perfis_por_numero = {worker.normalizar(self.NUMERO): self.RESTRITO}
        with mock.patch.object(worker, "api", return_value=(502, None)):
            worker.sincronizar_telefones()
        self.assertEqual(worker.tenants_do_numero(self.NUMERO), self.RESTRITO)


if __name__ == "__main__":
    unittest.main()
