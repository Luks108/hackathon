"""Os dados que o pacote de prova precisa: o evento `fonte` com a cadeia até o arquivo bruto e o `fim`/`erro` com o modelo.
Sem internet e sem gastar token.

    python -m unittest discover -s chat/testes -v
"""
import importlib
import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import agente  # noqa: E402
import provedores  # noqa: E402

TENANTS = ["pe-estado", "pe-garanhuns"]
HASH = "a" * 64


def resultado_de_conferir(**extra):
    """O que conferir_evidencia devolve (consulta/mcp_transparencia.py), campo a campo."""
    e = {"trecho": "Contrato 12/2024 | Empresa Alfa | R$ 120.000,00", "url": "https://portal.exemplo/c", "arquivo": "contratos-2024.html",
         "documento_hash": HASH, "tabela": "contratos", "linha": 7, "capturado_em": "2026-11-05", "trecho_mascarado": False, "hash_confere": True}
    e.update(extra)
    return e


def fontes_de(resultado):
    leitor = agente.Leitor()
    leitor.ler({"type": "assistant", "message": {"content": [
        {"type": "tool_use", "id": "t1", "name": agente.PREFIXO + "conferir_evidencia", "input": {"evidencia_id": "abc:contratos:7"}}]}})
    return leitor.ler({"type": "user", "message": {"content": [
        {"type": "tool_result", "tool_use_id": "t1", "content": [{"type": "text", "text": json.dumps(resultado)}]}]}})


class TestFonteComCadeiaDeProva(unittest.TestCase):
    def test_fonte_leva_a_cadeia_ate_o_arquivo_bruto(self):
        (tipo, d), = fontes_de(resultado_de_conferir())
        self.assertEqual(tipo, "fonte")
        self.assertEqual((d["evidencia"], d["documento_hash"], d["arquivo"], d["tabela"], d["linha"]), ("abc:contratos:7", HASH, "contratos-2024.html", "contratos", 7))
        self.assertTrue(d["hash_confere"])
        self.assertFalse(d["trecho_mascarado"])

    def test_campos_antigos_continuam_como_eram(self):
        (_, d), = fontes_de(resultado_de_conferir())
        for campo in ("evidencia", "trecho", "url", "capturado_em", "hash_confere"):
            self.assertIn(campo, d)

    def test_arquivo_vira_so_o_nome_nunca_um_caminho(self):
        for sujo in (r"C:\Users\Rodri\Desktop\bruto\contratos-2024.html", "/var/www/dados/bruto/contratos-2024.html", "contratos-2024.html"):
            (_, d), = fontes_de(resultado_de_conferir(arquivo=sujo))
            self.assertEqual(d["arquivo"], "contratos-2024.html")
            self.assertFalse("/" in d["arquivo"] or "\\" in d["arquivo"])

    def test_dado_ausente_continua_ausente(self):
        r = resultado_de_conferir()
        for campo in ("documento_hash", "arquivo", "tabela", "linha"):
            r.pop(campo)
        (_, d), = fontes_de(r)
        self.assertEqual((d["documento_hash"], d["arquivo"], d["tabela"], d["linha"]), (None, None, None, None))

    def test_cpf_continua_mascarado_no_trecho(self):
        (_, d), = fontes_de(resultado_de_conferir(trecho="Titular 123.456.789-09 recebeu"))
        self.assertNotIn("123.456.789-09", d["trecho"])


class TestEventosFinaisLevamOModelo(unittest.TestCase):
    """O site só guarda o que o worker manda: quem respondeu e as trocas precisam ir no fim/erro."""

    @classmethod
    def setUpClass(cls):
        if not (Path(__file__).resolve().parents[2] / ".env").exists():
            raise unittest.SkipTest("o worker lê o .env ao ser importado")
        with mock.patch.dict(os.environ, {"WORKER_KEY": "k" * 30}):
            cls.worker = importlib.import_module("worker")

    def rodar(self, eventos_do_agente, modelo="a"):
        enviados = []

        def falso(texto, tenants, historico=None, leitor=None, **kw):
            leitor.modelo_pedido, leitor.modelo = "a", modelo
            leitor.tentados = ["a", modelo] if modelo != "a" else ["a"]
            if modelo != "a":
                leitor.trocas.append({"de": "a", "para": modelo, "motivo": "limite de uso do provedor atingido", "tentativa": 2})
            yield from eventos_do_agente

        api = lambda met, rota, corpo=None: (enviados.extend((corpo or {}).get("eventos", [])), (200, None))[1]  # noqa: E731
        with mock.patch.object(agente, "perguntar", falso), mock.patch.object(self.worker, "api", api), \
                mock.patch.object(self.worker, "gravar_log"):
            self.worker.atender_site({"id": 1, "usuario_id": 1, "texto": "oi", "tenants": TENANTS})
        return enviados

    def test_fim_leva_modelo_pedido_modelo_tentados_e_trocas(self):
        eventos = self.rodar([("texto", {"delta": "Olá."}), ("fim", {"duracao_ms": 10})], modelo="b")
        fim = next(e for e in eventos if e["tipo"] == "fim")["dados"]
        self.assertEqual((fim["modelo_pedido"], fim["modelo"], fim["tentados"]), ("a", "b", ["a", "b"]))
        self.assertEqual(fim["trocas"], [{"de": "a", "para": "b", "motivo": "limite de uso do provedor atingido", "tentativa": 2}])
        self.assertEqual(fim["duracao_ms"], 10)       # o campo de antes continua

    def test_erro_tambem_leva_o_modelo_e_mantem_a_mensagem_padrao(self):
        eventos = self.rodar([("erro", {"motivo": "provedor com problema"})])
        erro = next(e for e in eventos if e["tipo"] == "erro")["dados"]
        self.assertEqual(erro["motivo"], self.worker.ERRO_PADRAO)
        self.assertEqual((erro["modelo_pedido"], erro["trocas"]), ("a", []))

    def test_sem_troca_trocas_vai_vazio_e_nao_inventada(self):
        fim = next(e for e in self.rodar([("texto", {"delta": "x"}), ("fim", {"duracao_ms": 1})]) if e["tipo"] == "fim")["dados"]
        self.assertEqual(fim["trocas"], [])
        self.assertEqual(fim["tentados"], ["a"])


if __name__ == "__main__":
    unittest.main()
