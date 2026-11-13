"""Busca por texto: transforma o que o usuário digitou numa consulta do índice de texto (Lucene) do Neo4j, sem abrir a porta para a sintaxe dela.

O termo vem do modelo, que o copia da pergunta do usuário: é texto de fora. Aqui ele vira só palavras minúsculas, sem acento, com letras e dígitos,
e nada mais chega ao Lucene: `+ - ! ( ) { } [ ] ^ " ~ * ? : \\ /` e os operadores `AND`, `OR`, `NOT` (que só valem em maiúsculas) nunca passam.
Quem escreve os operadores é este arquivo, nunca o usuário.

Cada palavra casa de três jeitos: inteira, por prefixo (quem digita "bromel") e com um erro de digitação (`~1`, só em palavras de 5 letras ou mais).
Todas as palavras têm de aparecer (AND): "zeta omega engenharia" não devolve toda empresa de engenharia, porque a base é uma amostra e uma
busca frouxa demais faria o modelo "achar" uma empresa que não é a da pergunta.
"""

import re
import unicodedata

MAX_PALAVRAS = 6          # palavras além disso são ignoradas: o nome de uma empresa não precisa de mais
TAMANHO_PARA_ERRO = 5     # palavra menor que isso não admite erro de digitação (casaria com palavra parecida demais)
TAMANHO_PARA_PREFIXO = 3  # e menor que isso só casa inteira


def sem_acento(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", str(texto or "")) if not unicodedata.combining(c)).lower()


def palavras(texto: str) -> list[str]:
    """As palavras da busca: minúsculas, sem acento, só letras e dígitos, com pelo menos 2 caracteres."""
    return re.findall(r"[a-z0-9]{2,}", sem_acento(texto))[:MAX_PALAVRAS]


def para_lucene(texto: str) -> str | None:
    """A consulta do índice de texto, ou None se não sobrou nenhuma palavra (o chamador devolve vazio)."""
    achadas = palavras(texto)
    if not achadas:
        return None
    partes = []
    for p in achadas:
        if len(p) >= TAMANHO_PARA_ERRO:
            partes.append(f"({p}* OR {p}~1)")
        elif len(p) >= TAMANHO_PARA_PREFIXO:
            partes.append(f"{p}*")
        else:
            partes.append(p)
    return " AND ".join(partes)
