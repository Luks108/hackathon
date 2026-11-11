#!/usr/bin/env python3
"""Confere se o diário de sessões segue o padrão e se não vaza segredo. Só biblioteca padrão.

    python docs/sessoes/validar.py                 # todos os arquivos datados da pasta
    python docs/sessoes/validar.py ARQUIVO [...]   # só estes

Sai com código 1 se algum arquivo tiver problema. O padrão é o de `_modelo.md`: nome, título, campos e seções na mesma ordem.
"""

import re
import sys
from datetime import date
from pathlib import Path

PASTA = Path(__file__).resolve().parent
NOME = re.compile(r"^(\d{4})-(\d{2})-(\d{2})-([a-z0-9]+(?:-[a-z0-9]+)*)\.md$")
CAMPOS = ["**Quem:**", "**Branch e commit de partida:**", "**Máquina e ambiente:**"]
SECOES = [
    "Resumo", "Feito", "Verificado (e como)", "Não verificado", "Decisões e motivo",
    "Em aberto (por prioridade)", "Resolvido de sessões anteriores", "Armadilhas", "Próximo passo sugerido",
]
SEGREDOS = [
    (r"(?<![\w.])sk-[A-Za-z0-9_-]{16,}", "chave de API (sk-...)"),
    (r"AIza[0-9A-Za-z_-]{20,}", "chave do Google"),
    (r"gh[pousr]_[A-Za-z0-9]{20,}", "token do GitHub"),
    (r"xox[baprs]-[A-Za-z0-9-]{10,}", "token do Slack"),
    (r"AKIA[0-9A-Z]{16}", "chave da AWS"),
    (r"(?i)\b[A-Z0-9_]*(?:KEY|SENHA|TOKEN|SECRET|PASSWORD)[A-Z0-9_]*\s*[=:]\s*(?!<)[^\s`'\"]{8,}", "valor de segredo (NOME=valor)"),
    (r"(?<![\w.-])[\w.+-]+@(?!anthropic\.com)[\w-]+\.[\w.-]+", "e-mail"),
    (r"(?<!\d)\+?55\d{10,11}(?!\d)", "número de telefone"),
    (r"\(\d{2}\)\s?9?\d{4}-?\d{4}", "número de telefone"),
    (r"(?<!\d)\d{3}\.\d{3}\.\d{3}-\d{2}(?!\d)", "CPF"),
]


def linhas_fora_de_codigo(texto: str):
    """(número, linha) de tudo que não está dentro de um bloco ``` ."""
    dentro = False
    for n, linha in enumerate(texto.splitlines(), 1):
        if linha.lstrip().startswith("```"):
            dentro = not dentro
            continue
        if not dentro:
            yield n, linha


def conferir(caminho: Path) -> list[str]:
    problemas: list[str] = []
    m = NOME.match(caminho.name)
    if not m:
        return [f"nome fora do padrão (esperado AAAA-MM-DD-usuario.md, minúsculas, sem acento): {caminho.name}"]
    try:
        date(int(m[1]), int(m[2]), int(m[3]))
    except ValueError:
        problemas.append(f"data inválida no nome: {m[1]}-{m[2]}-{m[3]}")
    texto = caminho.read_text(encoding="utf-8")
    linhas = list(linhas_fora_de_codigo(texto))

    esperado = f"# {m[1]}-{m[2]}-{m[3]}: {m[4]}"
    primeira = texto.splitlines()[0].strip() if texto.strip() else ""
    if primeira != esperado:
        problemas.append(f"a primeira linha deve ser exatamente '{esperado}' (está '{primeira[:60]}')")

    for campo in CAMPOS:
        if not any(l.lstrip("- ").startswith(campo) for _, l in linhas):
            problemas.append(f"falta o campo '- {campo}'")

    titulos = [l[3:].strip() for _, l in linhas if l.startswith("## ")]
    posicao = -1
    for secao in SECOES:
        if secao not in titulos:
            problemas.append(f"falta a seção '## {secao}'")
            continue
        i = titulos.index(secao)
        if i < posicao:
            problemas.append(f"a seção '## {secao}' está fora da ordem do modelo")
        posicao = max(posicao, i)

    for n, linha in enumerate(texto.splitlines(), 1):
        for padrao, descricao in SEGREDOS:
            if re.search(padrao, linha):
                problemas.append(f"linha {n}: possível {descricao}. O diário é versionado; cite só o nome da variável")
    return problemas


def main(argumentos: list[str]) -> int:
    arquivos = [Path(a) for a in argumentos] or sorted(p for p in PASTA.glob("*.md") if NOME.match(p.name))
    falhou = False
    for arquivo in arquivos:
        problemas = conferir(arquivo)
        print(f"{'ERRO' if problemas else 'ok  '} {arquivo}")
        for p in problemas:
            print(f"       - {p}")
        falhou = falhou or bool(problemas)
    return 1 if falhou else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
