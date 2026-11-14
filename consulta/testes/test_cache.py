"""bench/cache.py: a medição do cache a partir do log. Sem modelo e sem rede.

    python -m unittest discover -s consulta/testes -v
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "bench"))
import cache  # noqa: E402


def fim(ts, modelo="claude-sonnet-5-5", entrada=1000, lido=0, escrito=0, consultas=0, rodadas=1, resultado="ok", custo=0.01):
    return {"ts": ts, "evento": "tentativa_fim", "modelo": modelo, "resultado": resultado, "tokens_entrada": entrada, "tokens_saida": 10,
            "cache_lido": lido, "cache_escrito": escrito, "consultas": consultas, "rodadas": rodadas, "custo_usd": custo}


class TestCarregar(unittest.TestCase):
    def arquivo(self, linhas):
        pasta = tempfile.TemporaryDirectory()
        self.addCleanup(pasta.cleanup)
        caminho = Path(pasta.name) / "agente.jsonl"
        caminho.write_text("\n".join(l if isinstance(l, str) else json.dumps(l) for l in linhas), encoding="utf-8")
        return caminho

    def test_so_tentativas_ok_com_tokens_em_ordem_de_tempo(self):
        c = self.arquivo([fim("2026-11-13T10:00:02-03:00"), fim("2026-11-13T10:00:01-03:00"), fim("2026-11-13T10:00:03-03:00", resultado="falha"),
                          {"evento": "tentativa_fim", "ts": "2026-11-13T10:00:04-03:00", "resultado": "ok", "modelo": "x"},
                          {"evento": "resumo", "ts": "x", "tokens_entrada": 5}, "linha quebrada {", ""])
        self.assertEqual([d["ts"][-14:-6] for d in cache.carregar(c)], ["10:00:01", "10:00:02"])


class TestResumo(unittest.TestCase):
    def test_taxa_de_acerto_e_medias(self):
        r = cache.resumo([fim("a", entrada=1000, lido=800, escrito=100, custo=0.02), fim("b", entrada=3000, lido=1200, escrito=500, custo=0.04)])
        self.assertAlmostEqual(r["acerto"], 2000 / 4000)          # soma do lido / soma da entrada, não média de taxas
        self.assertEqual((r["n"], r["entrada"], r["lido"], r["escrito"]), (2, 2000, 1000, 300))
        self.assertAlmostEqual(r["custo"], 0.03)

    def test_sem_cache_informado_conta_zero_e_nao_quebra(self):
        d = fim("a", entrada=500)
        d.pop("cache_lido"), d.pop("cache_escrito"), d.pop("custo_usd")
        r = cache.resumo([d])
        self.assertEqual((r["acerto"], r["escrito"], r["custo"]), (0, 0, 0))

    def test_faixas_por_numero_de_consultas(self):
        self.assertEqual([cache.faixa(fim("a", consultas=c)) for c in (0, 1, 2, 3, 4, 5, 9)],
                         ["0 consultas", "1-2 consultas", "1-2 consultas", "3-4 consultas", "3-4 consultas", "5+ consultas", "5+ consultas"])


class TestEntrePerguntas(unittest.TestCase):
    def test_separa_pelo_intervalo_desde_a_pergunta_anterior_do_mesmo_modelo(self):
        fins = [fim("2026-11-13T10:00:00-03:00"), fim("2026-11-13T10:00:10-03:00"),            # 10 s
                fim("2026-11-13T10:02:10-03:00"),                                              # 2 min
                fim("2026-11-13T10:12:10-03:00"),                                              # 10 min (passou o TTL)
                fim("2026-11-13T10:12:11-03:00", modelo="deepseek:x"),                         # outro modelo não conta
                fim("2026-11-13T10:12:12-03:00", consultas=2),                                 # tem consulta: fora
                fim("2026-11-13T10:12:13-03:00", rodadas=3)]                                   # várias rodadas: fora
        g = cache.entre_perguntas(fins, "claude-sonnet-5-5")
        self.assertEqual({k: len(v) for k, v in g.items()}, {"<= 30 s": 1, "30 s a 5 min": 1, "> 5 min (passou o TTL)": 1})

    def test_a_primeira_pergunta_nao_tem_anterior(self):
        self.assertEqual(sum(map(len, cache.entre_perguntas([fim("2026-11-13T10:00:00-03:00")], "claude-sonnet-5-5").values())), 0)


class TestRelatorio(unittest.TestCase):
    def test_roda_sobre_um_log_e_sem_log_avisa(self):
        pasta = tempfile.TemporaryDirectory()
        self.addCleanup(pasta.cleanup)
        caminho = Path(pasta.name) / "agente.jsonl"
        caminho.write_text(json.dumps(fim("2026-11-13T10:00:00-03:00", lido=500, entrada=1000)), encoding="utf-8")
        self.assertEqual(cache.main([str(caminho)]), 0)
        caminho.write_text("", encoding="utf-8")
        self.assertEqual(cache.main([str(caminho)]), 1)


if __name__ == "__main__":
    unittest.main()
