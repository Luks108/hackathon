"""Separa 10 contratos que cobrem os casos da demo, com tudo que eles referenciam.

    .venv/bin/python coleta/amostra.py
"""

import json
from pathlib import Path

DADOS = Path(__file__).resolve().parents[1] / "dados"
SAIDA = DADOS / "amostra"


def ler(nome: str) -> list[dict]:
    return [json.loads(l) for l in (DADOS / f"{nome}.jsonl").read_text(encoding="utf-8").splitlines()]


def main() -> None:
    contratos, processos, fornecedores, sancoes, evidencias = map(
        ler, ("contratos", "processos", "fornecedores", "sancoes", "evidencias"))
    sancionados = {s["fornecedor"] for s in sancoes}
    processos_ids = {p["id"] for p in processos}
    pj = [c for c in contratos if c["sensibilidade"] == "publico" and c["fornecedor"].startswith("cnpj:")]
    pj.sort(key=lambda c: -c["valor_contratado"])

    casos = [
        (3, "com_sancao", lambda c: c["fornecedor"] in sancionados),
        (3, "com_processo", lambda c: c["processo"] in processos_ids and c["fornecedor"] not in sancionados),
        (2, "sem_processo", lambda c: not c["processo_informado"] and c["fornecedor"] not in sancionados),
        (1, "com_aditivo", lambda c: c["tem_aditivo"] and c["fornecedor"] not in sancionados),
    ]
    escolhidos: list[dict] = []
    usados: set[str] = set()
    for quantos, caso, regra in casos:
        achados = 0
        for c in pj:
            if achados < quantos and c["fornecedor"] not in usados and regra(c):
                escolhidos.append({**c, "caso_demo": caso})
                usados.add(c["fornecedor"])
                achados += 1
    pf = next(c for c in contratos if c["sensibilidade"] == "pessoal" and c["fornecedor"].startswith("pf:"))
    escolhidos.append({**pf, "caso_demo": "pessoa_fisica"})
    usados.add(pf["fornecedor"])

    sanc = [s for s in sancoes if s["fornecedor"] in usados]
    procs = [p for p in processos if p["id"] in {c["processo"] for c in escolhidos}]
    evs = {c["evidencia"] for c in escolhidos} | {s["evidencia"] for s in sanc} | {p["evidencia"] for p in procs}
    SAIDA.mkdir(exist_ok=True)
    conjuntos = {
        "contratos": escolhidos,
        "processos": procs,
        "sancoes": sanc,
        "fornecedores": [f for f in fornecedores if f["id"] in usados and f["evidencia"] in evs],
        "evidencias": [e for e in evidencias if e["id"] in evs],
    }
    for nome, itens in conjuntos.items():
        (SAIDA / f"{nome}.jsonl").write_text("".join(json.dumps(i, ensure_ascii=False) + "\n" for i in itens))
    print({k: len(v) for k, v in conjuntos.items()})
    for c in escolhidos:
        print(c["caso_demo"], c["tipo"] if "tipo" in c else "", round(c["valor_contratado"], 2), bool(c["processo"]))


if __name__ == "__main__":
    main()
