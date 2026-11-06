"""Gera dados/painel.json, o conteúdo da área técnica servido só com login.

    .venv/bin/python consulta/gerar_painel.py

Junta o texto de site/painel/conteudo.html, o grafo do Neo4j, o benchmark e o teste de carga.
Pessoa física fica de fora, e o arquivo não é versionado: cita fornecedores reais.
"""

import csv
import io
import json
import re
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "consulta"))
from pagina_do_grafo import ler_grafo  # noqa: E402

CPF = re.compile(r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b")
CONTATO = {"PESSFONE_NU_DDD", "PESSFONE_NU_FONE", "LOGR_NM", "PESSEND_NU_LOGRADOURO", "PESSEND_DS_COMPLEMENTO",
           "BAIRRO_NM", "LOGRSECAO_NU_CEP"}
INVENTARIO = [
    ("Contratos do Estado, 2024", "pe-contratos-2024.json", "JSON", "2.047 contratos em 70 órgãos", "Estruturado; 70 no grafo", "lido"),
    ("Execução por fornecedor, 2024", "pe-execucao-2024.json", "JSON", "721 linhas de 62 CNPJs da amostra", "Estruturado e no grafo", "lido"),
    ("Execução por fornecedor, 2025", "pe-execucao-2025.json", "JSON", "746 linhas de CNPJs da amostra", "Estruturado e no grafo", "lido"),
    ("Volume de contratos do Estado", "pe-volumes.json", "JSON", "25.947 contratos de 2019 a 2024", "Só medido", "derivado"),
    ("Contratos de Garanhuns", "contratos-2026.html", "HTML", "756 linhas", "Estruturado; 30 no grafo", "lido"),
    ("Licitações de Garanhuns", "licitacoes-2026.html", "HTML", "240 licitações", "Estruturado; parte no grafo", "lido"),
    ("Sanções do Estado", "pe-sancionados.csv", "CSV", "3.071 ocorrências", "Estruturado; 95 no grafo", "lido"),
    ("Fiscais de Garanhuns", "fiscais-2026-SENSIVEL.html", "HTML", "756 linhas", "Usado só para resolver o documento", "lido"),
    ("Diárias de Garanhuns", "diarias-2026.html", "HTML", "1.065 linhas", "Capturado, não estruturado", "derivado"),
    ("Obras de Garanhuns", "obras.html", "HTML", "82 linhas", "Capturado, não estruturado", "derivado"),
    ("Legislação de Garanhuns", "legislacao.html", "HTML", "1.748 linhas", "Capturado, não estruturado", "derivado"),
    ("Ordens bancárias do Estado", "pe-painel-pagamentos.html", "Painel", "Consulta devolveu 0 linhas", "Sem dado; ligação com contrato não confirmada", "derivado"),
]


def bruto_dir() -> Path:
    for linha in (RAIZ / ".env").read_text(encoding="utf-8").splitlines():
        if linha.startswith("BRUTO="):
            return Path(linha.split("=", 1)[1].strip())
    raise SystemExit("BRUTO ausente no .env")


def linha_jsonl(arquivo: Path, campo: str, valor: str) -> dict:
    return next(r for r in map(json.loads, arquivo.read_text(encoding="utf-8").splitlines()) if r.get(campo) == valor)


def inventario(bruto: Path) -> list[dict]:
    saida = []
    for nome, arquivo, formato, volume, estado, selo in INVENTARIO:
        kb = (bruto / arquivo).stat().st_size / 1024
        tamanho = f"{kb / 1024:.1f} MB".replace(".", ",") if kb >= 1024 else f"{kb:.0f} KB"
        saida.append(dict(nome=nome, formato=formato, tamanho=tamanho, volume=volume, estado=estado, selo=selo))
    return saida


def exemplo_estado(bruto: Path, contratos: list[dict], amostra: Path) -> dict:
    """Um contrato do Estado, com a linha do painel como veio e a execução do mesmo fornecedor."""
    execucoes = [json.loads(x) for x in (amostra / "execucoes.jsonl").read_text(encoding="utf-8").splitlines()]
    com_execucao = {x["fornecedor"] for x in execucoes}
    c = next(x for x in contratos if x["tenant"] == "pe-estado" and x["sensibilidade"] == "publico" and x["fornecedor"] in com_execucao)
    x = next(y for y in execucoes if y["fornecedor"] == c["fornecedor"])
    ev = linha_jsonl(amostra / "evidencias.jsonl", "id", c["evidencia"])
    arquivo = json.loads((bruto / ev["arquivo"]).read_text(encoding="utf-8"))
    nomes = ["orgao", "contrato", "objeto", "vazio", "situacao", "processo", "credor", "inicio", "fim", "valor", "download"]
    cru = dict(zip(nomes, arquivo["linhas"][ev["linha"] - 1]))
    cru.pop("vazio")
    limpar = lambda r, fora: {k: v for k, v in r.items() if k not in fora}  # noqa: E731
    return {
        "cru_estado": json.dumps(cru, ensure_ascii=False, indent=2),
        "fato_contrato_estado": limpar(c, {"caso_demo", "uj", "idc"}),
        "fato_execucao": limpar(x, {"uj"}),
    }


def exemplo(bruto: Path) -> dict:
    """Um fornecedor real da amostra, da fonte até o grafo, sem nome de fiscal nem contato."""
    amostra = RAIZ / "dados" / "amostra"
    contratos = [json.loads(x) for x in (amostra / "contratos.jsonl").read_text(encoding="utf-8").splitlines()]
    sancoes = [json.loads(x) for x in (amostra / "sancoes.jsonl").read_text(encoding="utf-8").splitlines()]
    c = next(x for x in contratos if x["tenant"] == "pe-garanhuns" and x["caso_demo"] == "com_sancao"
              and any(s["fornecedor"] == x["fornecedor"] for s in sancoes))
    s = next(x for x in sancoes if x["fornecedor"] == c["fornecedor"])
    evidencia = linha_jsonl(amostra / "evidencias.jsonl", "id", c["evidencia"])

    html = (bruto / "contratos-2026.html").read_text(encoding="utf-8", errors="replace")
    pos = html.index(f"idc={c['idc']}")
    tr = html[html.rfind("<tr", 0, pos):html.index("</tr>", pos) + 5]
    tr = re.sub(r"(Fiscal do Contrato:\s*<span[^>]*>)[^<]*", r"\1[nome removido]", tr)
    tr = re.sub(r"[ \t]+", " ", re.sub(r"\s*\n\s*", "\n", tr))[:1400] + "\n…"

    conteudo = (bruto / "pe-sancionados.csv").read_text(encoding="utf-8-sig")
    leitor = csv.DictReader(io.StringIO(conteudo), delimiter=";" if conteudo[:300].count(";") > 5 else ",")
    cod = s["id"].rsplit(":", 1)[1]
    linha = next(r for r in leitor if r["FORNOCORR_CD"] == cod)
    cru_csv = "\n".join(f"{k}: {'[contato removido]' if k in CONTATO else str(v)[:150]}" for k, v in linha.items())

    limpar = lambda r, fora: {k: v for k, v in r.items() if k not in fora}  # noqa: E731
    return {
        **exemplo_estado(bruto, contratos, amostra),
        "cru_contrato": tr, "cru_sancao": cru_csv,
        "fato_contrato": limpar(c, {"caso_demo", "uj"}), "fato_sancao": limpar(s, {"inicio_suspensao"}),
        "evidencia": evidencia,
        "caminho": [
            f"(Contrato {c['numero']}) -[:CONTRATA]-> (Fornecedor {c['fornecedor']})",
            f"(Contrato {c['numero']}) -[:CELEBRADO_POR]-> (Unidade {c['uj_nome']}) -[:PERTENCE_A]-> (Município de Garanhuns)",
            f"(Contrato {c['numero']}) -[:PROVADO_POR]-> (Evidência {c['evidencia']})",
            f"(Fornecedor {c['fornecedor']}) -[:RECEBEU]-> (Sanção {s['tipo']}, {s['situacao']})",
            f"(Sanção {s['tipo']}) -[:DO_ENTE]-> (Estado de Pernambuco)",
            f"(Sanção {s['tipo']}) -[:PROVADO_POR]-> (Evidência {s['evidencia']})",
        ],
    }


def main() -> int:
    bench = json.loads((RAIZ / "dados/bench/resultado.json").read_text(encoding="utf-8"))
    for linha in bench["linhas"]:
        linha["fontes"] = len(linha["fontes"])
        linha["consultas"] = len(linha["consultas"])
    bruto = bruto_dir()
    saida = {
        "inventario": inventario(bruto),
        "exemplo": exemplo(bruto),
        "html": (RAIZ / "site/painel/conteudo.html").read_text(encoding="utf-8"),
        "grafo": ler_grafo(),
        "benchmark": bench,
        "carga": json.loads((RAIZ / "dados/bench/carga.json").read_text(encoding="utf-8")),
    }
    texto = json.dumps(saida, ensure_ascii=False)
    if CPF.search(texto) or re.search(r"Fiscal do Contrato:\s*<span[^>]*>(?!\[nome removido\])", texto):
        print("ERRO: dado pessoal no painel; nada foi gravado", file=sys.stderr)
        return 1
    (RAIZ / "dados/painel.json").write_text(texto, encoding="utf-8")
    print(len(texto), "bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
