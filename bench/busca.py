"""Mede a busca de fornecedor: a de antes (`CONTAINS`) contra a do índice de texto, com as variações que um usuário digita.
Só LÊ o grafo (não grava nada, não chama modelo). Use com a base do benchmark carregada:

    python coleta/carregar_neo4j.py --zerar --benchmark
    python bench/busca.py

Dois números importam:
  - ACHOU: para cada variação de um nome que existe, o fornecedor certo veio entre os resultados?
  - FALSO POSITIVO: para um nome que NÃO existe (empresa inventada, ou palavras de duas empresas diferentes), veio algum resultado?
    A base é uma amostra e a resposta correta é "não localizei": uma busca frouxa faria o modelo achar uma empresa que não é a da pergunta.
"""

import os
import random
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "chat"))
sys.path.insert(0, str(RAIZ / "consulta"))
import agente  # noqa: E402  (carrega o .env e dá a conexão com o grafo)
import busca  # noqa: E402

ENTES = ["pe-estado", "pe-garanhuns"]
ANTES = """
    MATCH (f:Fornecedor)-[:APARECE_EM]->(e:Ente)
    WHERE e.id IN $tenants AND (f.tipo = 'PJ' OR size($sensibilidades) > 1)
      AND (toUpper(f.nome) CONTAINS toUpper($termo) OR ($digitos <> '' AND f.cnpj = $digitos))
    RETURN DISTINCT f.id AS id, f.nome AS nome LIMIT 10"""
DEPOIS = """
    CALL db.index.fulltext.queryNodes('fornecedor_nome', $consulta, {limit: 200}) YIELD node AS f, score
    MATCH (f)-[:APARECE_EM]->(e:Ente)
    WHERE e.id IN $tenants AND (f.tipo = 'PJ' OR size($sensibilidades) > 1)
    RETURN f.id AS id, f.nome AS nome, max(score) AS pontos ORDER BY pontos DESC LIMIT 10"""


def variacoes(nome: str) -> dict[str, str]:
    """Como alguém escreveria o nome de um fornecedor (o nome do cadastro traz '(fictícia)' no fim, que ninguém digita)."""
    limpo = nome.split("(")[0].strip()
    palavras = limpo.split()
    primeira = palavras[0]
    v = {
        "exato": nome,
        "sem o parêntese": limpo,
        "minúsculas": limpo.lower(),
        "sem acento": busca.sem_acento(limpo),
        "só a primeira palavra": primeira,
        "começo da palavra": primeira[:5],
        "sem o sufixo (Ltda)": " ".join(p for p in palavras if p.lower() != "ltda"),
    }
    if len(palavras) >= 3:
        v["ordem trocada"] = " ".join(reversed([p for p in palavras if p.lower() != "ltda"]))
        v["só o fim do nome"] = " ".join(palavras[1:-1] if palavras[-1].lower() == "ltda" else palavras[1:])
    if len(primeira) >= 6:
        v["uma letra a menos"] = primeira[:2] + primeira[3:] + " " + " ".join(palavras[1:])
        v["duas letras trocadas"] = primeira[:2] + primeira[3] + primeira[2] + primeira[4:] + " " + " ".join(palavras[1:])
    return v


def main() -> int:
    executar = agente._executar_no_grafo(ENTES, ["publico"])
    fornecedores = executar("MATCH (f:Fornecedor)-[:APARECE_EM]->(e:Ente) WHERE e.id IN $tenants AND f.tipo = 'PJ' "
                            "RETURN DISTINCT f.id AS id, f.nome AS nome ORDER BY id")
    if len(fornecedores) < 10:
        sys.exit(f"só {len(fornecedores)} fornecedores no grafo: carregue a base do benchmark (python coleta/carregar_neo4j.py --zerar --benchmark)")

    def antes(texto):
        digitos = "".join(c for c in texto if c.isdigit())
        return [r["id"] for r in executar(ANTES, termo=texto, digitos=digitos)]

    def depois(texto):
        q = busca.para_lucene(texto)
        return [r["id"] for r in executar(DEPOIS, consulta=q)] if q else []

    por_tipo: dict[str, list[tuple[bool, bool, int, int]]] = {}
    for f in fornecedores:
        for tipo, texto in variacoes(f["nome"]).items():
            a, d = antes(texto), depois(texto)
            por_tipo.setdefault(tipo, []).append((f["id"] in a, f["id"] in d, len(a), len(d)))
    print(f"{len(fornecedores)} fornecedores; ACHOU o fornecedor certo entre os resultados (antes = CONTAINS, depois = índice de texto)\n")
    print(f"{'variação':<24}{'antes':>8}{'depois':>9}{'resultados antes/depois (média)':>36}")
    total_a = total_d = n = 0
    for tipo, linhas in por_tipo.items():
        k = len(linhas)
        a, d = sum(x[0] for x in linhas), sum(x[1] for x in linhas)
        print(f"{tipo:<24}{a:>5}/{k:<3}{d:>6}/{k:<3}{sum(x[2] for x in linhas) / k:>22.1f} /{sum(x[3] for x in linhas) / k:>6.1f}")
        total_a, total_d, n = total_a + a, total_d + d, n + k
    print(f"{'TOTAL':<24}{total_a:>5}/{n:<3}{total_d:>6}/{n:<3}\n")

    # Nomes que NÃO existem: nada pode vir.
    gerador = random.Random(13)
    inventados = ["Zeta Omega Engenharia de Sistemas", "Lua Nova Transportes", "Pitanga Digital", "Mandacaru Logistica", "Cajueiro Tecnologia",
                  "Zé do Boi Construções", "Nordeste Quimica Industrial"]
    nomes = [f["nome"].split("(")[0].replace("Ltda", "").split() for f in fornecedores]
    misturados = []
    existentes = {tuple(p[:1] + p[-1:]) for p in nomes if len(p) >= 2}
    for _ in range(40):
        a, b = gerador.sample(nomes, 2)
        if len(a) >= 2 and len(b) >= 2 and (a[0], b[-1]) not in existentes and a[0] != b[0] and a[-1] != b[-1]:
            misturados.append(f"{a[0]} {b[-1]}")
    falsos = {"antes": [], "depois": []}
    for texto in inventados + misturados:
        for chave, f in (("antes", antes), ("depois", depois)):
            if f(texto):
                falsos[chave].append(texto)
    print(f"FALSO POSITIVO (nome que não existe e veio resultado), em {len(inventados) + len(misturados)} nomes inventados ou misturados:")
    for chave in ("antes", "depois"):
        print(f"  {chave}: {len(falsos[chave])}" + (f"  {falsos[chave][:6]}" if falsos[chave] else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
