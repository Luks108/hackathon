"""Gera dados/painel.json, o conteúdo da área técnica servido só com login.

    .venv/bin/python consulta/gerar_painel.py

Junta o texto de site/painel/conteudo.html, o grafo do Neo4j, o benchmark e o teste de carga.
Pessoa física fica de fora, e o arquivo não é versionado: cita fornecedores reais.
"""

import json
import re
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "consulta"))
from pagina_do_grafo import ler_grafo  # noqa: E402

CPF = re.compile(r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b")


def main() -> int:
    bench = json.loads((RAIZ / "dados/bench/resultado.json").read_text(encoding="utf-8"))
    for linha in bench["linhas"]:
        linha["fontes"] = len(linha["fontes"])
        linha["consultas"] = len(linha["consultas"])
    saida = {
        "html": (RAIZ / "site/painel/conteudo.html").read_text(encoding="utf-8"),
        "grafo": ler_grafo(),
        "benchmark": bench,
        "carga": json.loads((RAIZ / "dados/bench/carga.json").read_text(encoding="utf-8")),
    }
    texto = json.dumps(saida, ensure_ascii=False)
    if CPF.search(texto):
        print("ERRO: CPF no painel; nada foi gravado", file=sys.stderr)
        return 1
    (RAIZ / "dados/painel.json").write_text(texto, encoding="utf-8")
    print(len(texto), "bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
