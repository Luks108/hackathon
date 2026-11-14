"""Mede o cache de prompt do agente a partir de logs/agente.jsonl. Só LÊ o log: não chama modelo e não gasta crédito.

    python bench/cache.py                    # logs/agente.jsonl
    python bench/cache.py caminho/outro.jsonl

Mostra, por modelo e por tipo de pergunta (quantas consultas fez): quantos tokens de entrada, quantos vieram do cache (`cache_lido`), quantos foram
escritos nele (`cache_escrito`), a taxa de acerto e o custo. E, para o Claude, o efeito ENTRE perguntas: uma pergunta de uma rodada só, sem consulta,
é só prompt + definição das tools + pergunta; se o cache funcionasse inteiro entre perguntas, quase tudo seria lido e quase nada escrito.

`tokens_entrada` é tudo o que o modelo leu (inclui o cache) somado em todas as rodadas da pergunta: uma pergunta com 6 rodadas relê o prefixo 6 vezes.
"""

import datetime
import json
import statistics
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
FAIXAS = (("0 consultas", 0, 0), ("1-2 consultas", 1, 2), ("3-4 consultas", 3, 4), ("5+ consultas", 5, 10_000))
TTL_S = 300      # o cache do Claude vale 5 minutos (padrão)


def carregar(caminho: Path) -> list[dict]:
    """As tentativas que terminaram bem e informaram tokens, em ordem de tempo."""
    fins = []
    for linha in caminho.read_text(encoding="utf-8").splitlines():
        if '"tentativa_fim"' not in linha:
            continue
        try:
            dado = json.loads(linha)
        except json.JSONDecodeError:
            continue
        if dado.get("evento") == "tentativa_fim" and dado.get("resultado") == "ok" and "tokens_entrada" in dado:
            fins.append(dado)
    return sorted(fins, key=lambda d: d["ts"])


def faixa(d: dict) -> str:
    c = d.get("consultas") or 0
    return next(nome for nome, de, ate in FAIXAS if de <= c <= ate)


def resumo(grupo: list[dict]) -> dict:
    n = len(grupo)
    entrada = sum(g["tokens_entrada"] for g in grupo)
    lido = sum(g.get("cache_lido") or 0 for g in grupo)
    escrito = sum(g.get("cache_escrito") or 0 for g in grupo)
    return {"n": n, "entrada": entrada / n, "lido": lido / n, "escrito": escrito / n, "acerto": lido / entrada if entrada else 0.0,
            "rodadas": statistics.mean(g.get("rodadas") or 1 for g in grupo), "custo": statistics.mean(g.get("custo_usd") or 0 for g in grupo)}


def linha(nome: str, r: dict) -> str:
    return (f"  {nome:<34} n={r['n']:>4}  entrada={r['entrada']:>7.0f}  lido={r['lido']:>7.0f}  escrito={r['escrito']:>6.0f}  "
            f"ACERTO={r['acerto']:>6.1%}  rodadas={r['rodadas']:.1f}  US$/pergunta={r['custo']:.4f}")


def segundos(d: dict) -> float:
    return datetime.datetime.fromisoformat(d["ts"]).timestamp()


def entre_perguntas(fins: list[dict], modelo: str) -> dict[str, list[dict]]:
    """Perguntas de uma rodada só e sem consulta, separadas pelo intervalo desde a pergunta anterior do mesmo modelo."""
    grupos: dict[str, list[dict]] = {"<= 30 s": [], "30 s a 5 min": [], "> 5 min (passou o TTL)": []}
    anterior = None
    for d in (x for x in fins if x["modelo"] == modelo):
        agora = segundos(d)
        if anterior is not None and d.get("rodadas") == 1 and not d.get("consultas"):
            gap = agora - anterior
            grupos["<= 30 s" if gap <= 30 else "30 s a 5 min" if gap <= TTL_S else "> 5 min (passou o TTL)"].append(d)
        anterior = agora
    return grupos


def main(argv: list[str]) -> int:
    caminho = Path(argv[0]) if argv else RAIZ / "logs" / "agente.jsonl"
    fins = carregar(caminho)
    if not fins:
        print(f"nenhuma tentativa com tokens em {caminho}")
        return 1
    modelos = sorted({d["modelo"] for d in fins})
    print(f"{len(fins)} tentativas de {fins[0]['ts'][:16]} a {fins[-1]['ts'][:16]}\n\nTaxa de acerto do cache por modelo e tipo de pergunta (cache_lido / tokens_entrada):")
    for m in modelos:
        print(linha(m, resumo([d for d in fins if d["modelo"] == m])))
        for nome, _, _ in FAIXAS:
            g = [d for d in fins if d["modelo"] == m and faixa(d) == nome]
            if g:
                print(linha("   " + nome, resumo(g)))
    print("\nO cache funciona entre perguntas? (uma rodada, sem consulta = prompt + tools + pergunta):")
    for m in (x for x in modelos if x.startswith("claude")):
        for nome, g in entre_perguntas(fins, m).items():
            if g:
                print(linha(f"{m} / intervalo {nome}", resumo(g)))
    print("\nPeso do prompt fixo (tokens de entrada, uma rodada, sem consulta):")
    for m in modelos:
        g = [d["tokens_entrada"] for d in fins if d["modelo"] == m and d.get("rodadas") == 1 and not d.get("consultas")]
        if g:
            print(f"  {m:<28} n={len(g):>4}  mínimo={min(g)}  mediana={statistics.median(g):.0f}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
