"""Projeta os fatos extraídos no Neo4j. O grafo é descartável: --zerar reconstrói tudo.

    .venv/bin/python coleta/carregar_neo4j.py [--zerar] [--amostra | --exemplo]
"""

import json
import os
import sys
from pathlib import Path

from neo4j import GraphDatabase

RAIZ = Path(__file__).resolve().parents[1]
for linha in (RAIZ / ".env").read_text().splitlines():
    if "=" in linha:
        k, v = linha.split("=", 1)
        os.environ.setdefault(k, v)

DADOS = RAIZ / "dados" / ("amostra" if "--amostra" in sys.argv else "")
if "--exemplo" in sys.argv:  # dados fictícios, versionados, para quem não tem a captura
    DADOS = RAIZ / "fixtures" / "exemplo"
LOTE = 500

ENTES = [
    {"id": "pe-garanhuns", "nome": "Município de Garanhuns", "esfera": "municipal", "uf": "PE"},
    {"id": "pe-estado", "nome": "Estado de Pernambuco", "esfera": "estadual", "uf": "PE"},
]

# Um fornecedor pode ter nome só numa fonte: coalesce não apaga o nome já gravado.
CARGAS = [
    ("evidencias", """
        UNWIND $linhas AS l
        MERGE (e:Evidencia {id: l.id})
        SET e += l.props"""),
    ("fornecedores", """
        UNWIND $linhas AS l
        MERGE (f:Fornecedor {id: l.id})
        SET f.tipo = l.tipo, f.cnpj = coalesce(l.cnpj, f.cnpj), f.nome = coalesce(l.nome, f.nome),
            f.resolvido = l.resolvido
        WITH f, l
        MATCH (e:Evidencia {id: l.evidencia})
        MERGE (f)-[:PROVADO_POR]->(e)
        WITH f, l
        MATCH (t:Ente {id: l.tenant})
        MERGE (f)-[:APARECE_EM]->(t)"""),
    ("processos", """
        UNWIND $linhas AS l
        MERGE (p:ProcessoLicitatorio {id: l.id})
        SET p += l.props
        WITH p, l
        MATCH (e:Evidencia {id: l.evidencia})
        MERGE (p)-[:PROVADO_POR]->(e)
        WITH p, l
        MATCH (t:Ente {id: l.tenant})
        MERGE (p)-[:DO_ENTE]->(t)"""),
    ("contratos", """
        UNWIND $linhas AS l
        MERGE (u:UnidadeJurisdicionada {id: l.uj})
        SET u.nome = l.uj_nome, u.tenant = l.tenant
        MERGE (c:Contrato {id: l.id})
        SET c += l.props
        WITH c, u, l
        MATCH (t:Ente {id: l.tenant})
        MERGE (u)-[:PERTENCE_A]->(t)
        MERGE (c)-[:CELEBRADO_POR]->(u)
        WITH c, l
        MATCH (f:Fornecedor {id: l.fornecedor})
        MERGE (c)-[:CONTRATA]->(f)
        WITH c, l
        MATCH (e:Evidencia {id: l.evidencia})
        MERGE (c)-[:PROVADO_POR]->(e)
        WITH c, l
        OPTIONAL MATCH (p:ProcessoLicitatorio {id: l.processo})
        FOREACH (_ IN CASE WHEN p IS NULL THEN [] ELSE [1] END | MERGE (c)-[:DECORRE_DE]->(p))"""),
    ("sancoes", """
        UNWIND $linhas AS l
        MERGE (s:Sancao {id: l.id})
        SET s += l.props
        WITH s, l
        MATCH (f:Fornecedor {id: l.fornecedor})
        MERGE (f)-[:RECEBEU]->(s)
        WITH s, l
        MATCH (e:Evidencia {id: l.evidencia})
        MERGE (s)-[:PROVADO_POR]->(e)
        WITH s, l
        MATCH (t:Ente {id: l.tenant})
        MERGE (s)-[:DO_ENTE]->(t)"""),
]

# Campos que viram relação não ficam repetidos como propriedade do nó.
LIGACOES = {"evidencia", "fornecedor", "processo", "uj", "uj_nome"}


def lotes(itens: list, n: int):
    for i in range(0, len(itens), n):
        yield itens[i:i + n]


def main() -> int:
    driver = GraphDatabase.driver(os.environ["NEO4J_URI"], auth=("neo4j", os.environ["NEO4J_SENHA"]))
    with driver.session() as s:
        if "--zerar" in sys.argv:
            s.run("MATCH (n) CALL { WITH n DETACH DELETE n } IN TRANSACTIONS OF 1000 ROWS").consume()
        for comando in (RAIZ / "esquema/neo4j.cypher").read_text().split(";"):
            comando = "\n".join(l for l in comando.splitlines() if not l.strip().startswith("//")).strip()
            if comando:
                s.run(comando).consume()
        s.run("UNWIND $linhas AS l MERGE (e:Ente {id: l.id}) SET e += l", linhas=ENTES).consume()

        for nome, consulta in CARGAS:
            itens = [json.loads(l) for l in (DADOS / f"{nome}.jsonl").read_text().splitlines()]
            for lote in lotes(itens, LOTE):
                for item in lote:
                    item["props"] = {k: v for k, v in item.items() if k not in LIGACOES}
                s.run(consulta, linhas=lote).consume()
            print(f"{nome}: {len(itens)}")

        print("\nnós:", {r["rotulo"]: r["n"] for r in s.run(
            "MATCH (n) UNWIND labels(n) AS rotulo RETURN rotulo, count(*) AS n ORDER BY n DESC")})
        print("relações:", {r["tipo"]: r["n"] for r in s.run(
            "MATCH ()-[r]->() RETURN type(r) AS tipo, count(*) AS n ORDER BY n DESC")})
    driver.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
