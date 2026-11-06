"""Separa 100 contratos, 70 do Estado e 30 de Garanhuns, com tudo que eles referenciam.

    .venv/bin/python coleta/amostra.py

Critério fixo, para a seleção não depender de quem roda:
- fornecedores que aparecem nos dois entes, com um contrato em cada;
- fornecedores do Estado que constam no cadastro de sanções, em aberto primeiro;
- em Garanhuns, os casos com sanção, com processo, sem processo e com aditivo;
- o restante do Estado vem do maior contrato de cada órgão, em rodízio, para cobrir mais órgãos;
- pessoas físicas ficam na base para provar que o perfil as esconde.
Grava também a lista de CNPJs usada na coleta de execução financeira.
"""

import json
from collections import Counter
from pathlib import Path

DADOS = Path(__file__).resolve().parents[1] / "dados"
SAIDA = DADOS / "amostra"
ESTADO, GARANHUNS = "pe-estado", "pe-garanhuns"
META_ESTADO, META_GARANHUNS = 70, 30
PF_POR_ENTE = {ESTADO: 3, GARANHUNS: 2}
CRUZADOS = 12
SANCIONADOS_ESTADO = 20


def ler(nome: str) -> list[dict]:
    caminho = DADOS / f"{nome}.jsonl"
    return [json.loads(l) for l in caminho.read_text(encoding="utf-8").splitlines()] if caminho.exists() else []


class Selecao:
    def __init__(self):
        self.itens: list[dict] = []
        self.ids: set[str] = set()

    def por(self, c: dict, caso: str) -> None:
        if c["id"] not in self.ids:
            self.ids.add(c["id"])
            self.itens.append({**c, "caso_demo": caso})

    def do_ente(self, tenant: str) -> int:
        return sum(c["tenant"] == tenant for c in self.itens)


def main() -> None:
    contratos, processos, fornecedores, sancoes, execucoes, evidencias = map(
        ler, ("contratos", "processos", "fornecedores", "sancoes", "execucoes", "evidencias"))
    abertas = {s["fornecedor"] for s in sancoes if s["situacao"] == "EM ABERTO"}
    sancionados = {s["fornecedor"] for s in sancoes}
    processos_ids = {p["id"] for p in processos}
    ordem = lambda c: (-c["valor_contratado"], c["id"])  # noqa: E731
    pj = sorted((c for c in contratos if c["sensibilidade"] == "publico" and c["fornecedor"].startswith("cnpj:")), key=ordem)
    estado = [c for c in pj if c["tenant"] == ESTADO]
    garanhuns = [c for c in pj if c["tenant"] == GARANHUNS]
    primeiro_e = {c["fornecedor"]: c for c in reversed(estado)}
    primeiro_g = {c["fornecedor"]: c for c in reversed(garanhuns)}

    sel = Selecao()
    cruzados = sorted(primeiro_e.keys() & primeiro_g.keys(),
                      key=lambda f: (f not in sancionados, -primeiro_e[f]["valor_contratado"], f))
    for f in cruzados[:CRUZADOS]:
        sel.por(primeiro_e[f], "nos_dois_entes")
        sel.por(primeiro_g[f], "nos_dois_entes")

    com_sancao = sorted((f for f in primeiro_e if f in sancionados),
                        key=lambda f: (f not in abertas, -primeiro_e[f]["valor_contratado"], f))
    for f in com_sancao[:SANCIONADOS_ESTADO]:
        sel.por(primeiro_e[f], "com_sancao")

    casos = [
        (5, "com_sancao", lambda c: c["fornecedor"] in sancionados),
        (6, "com_processo", lambda c: c["processo"] in processos_ids),
        (3, "sem_processo", lambda c: not c["processo_informado"]),
        (2, "com_aditivo", lambda c: c["tem_aditivo"]),
    ]
    usados = {c["fornecedor"] for c in sel.itens}
    for quantos, caso, regra in casos:
        achados = 0
        for c in garanhuns:
            if achados < quantos and c["fornecedor"] not in usados and regra(c):
                sel.por(c, caso)
                usados.add(c["fornecedor"])
                achados += 1

    pf = [c for c in contratos if c["sensibilidade"] == "pessoal" and c["fornecedor"].startswith("pf:")]
    for tenant, n in PF_POR_ENTE.items():
        for c in sorted((x for x in pf if x["tenant"] == tenant), key=ordem)[:n]:
            sel.por(c, "pessoa_fisica")

    for c in garanhuns:     # completa Garanhuns com os maiores contratos ainda fora da seleção
        if sel.do_ente(GARANHUNS) < META_GARANHUNS:
            sel.por(c, "maior_contrato")

    por_orgao: dict[str, list[dict]] = {}
    for c in estado:
        por_orgao.setdefault(c["uj_nome"], []).append(c)
    while sel.do_ente(ESTADO) < META_ESTADO:
        for fila in sorted(por_orgao.values(), key=lambda f: ordem(f[0])):
            while fila and fila[0]["id"] in sel.ids:
                fila.pop(0)
            if fila and sel.do_ente(ESTADO) < META_ESTADO:
                sel.por(fila.pop(0), "maior_do_orgao")

    escolhidos = sel.itens
    forn = {c["fornecedor"] for c in escolhidos}
    sanc = [s for s in sancoes if s["fornecedor"] in forn]
    exec_ = [x for x in execucoes if x["fornecedor"] in forn]
    procs = [p for p in processos if p["id"] in {c["processo"] for c in escolhidos}]
    evs = {x["evidencia"] for grupo in (escolhidos, sanc, exec_, procs) for x in grupo}
    SAIDA.mkdir(exist_ok=True)
    conjuntos = {
        "contratos": escolhidos,
        "processos": procs,
        "sancoes": sanc,
        "execucoes": exec_,
        "fornecedores": [f for f in fornecedores if f["id"] in forn and f["evidencia"] in evs],
        "evidencias": [e for e in evidencias if e["id"] in evs],
    }
    for nome, itens in conjuntos.items():
        (SAIDA / f"{nome}.jsonl").write_text("".join(json.dumps(i, ensure_ascii=False) + "\n" for i in itens))
    cnpjs = sorted(f[5:] for f in forn if f.startswith("cnpj:"))
    (SAIDA / "cnpjs.txt").write_text("\n".join(cnpjs) + "\n")
    print({k: len(v) for k, v in conjuntos.items()}, "cnpjs", len(cnpjs))
    print(Counter((c["tenant"], c["caso_demo"]) for c in escolhidos))
    print("órgãos do Estado:", len({c["uj_nome"] for c in escolhidos if c["tenant"] == ESTADO}))
    print("valor Estado:", round(sum(c["valor_contratado"] for c in escolhidos if c["tenant"] == ESTADO)))


if __name__ == "__main__":
    main()
