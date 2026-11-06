#!/usr/bin/env python3
"""Gera a base de conhecimento do assistente a partir de documentos.

    python docs/apresentacao/gerar_conhecimento.py [pasta_dos_documentos]

Coloque os documentos na pasta `conhecimento/` (ao lado deste script) e rode o comando. Ele cria:

    conhecimento.json   a base, para quem quiser conferir ou reaproveitar
    conhecimento.js     o mesmo conteúdo, que a página demo-chat.html carrega sozinha

Formatos: .md, .txt, .docx e .json (lista de registros). .pdf só se `pypdf` estiver instalado
(pip install pypdf). Só usa a biblioteca padrão do Python, e o texto dos documentos é tratado como
dado: nada é executado.

Como o texto vira registros
- Cada título (# no Markdown, estilo "Título" no Word) abre um registro. Sem títulos, o texto é
  dividido por parágrafos.
- Linhas opcionais dentro de uma seção:  Pergunta:  Palavras-chave:  Origem:  Problema:  Solução:
"""

import argparse
import hashlib
import json
import re
import sys
import zipfile
from datetime import date, datetime
from pathlib import Path
from xml.etree import ElementTree as ET

AQUI = Path(__file__).resolve().parent
MAX_TEXTO = 1000   # caracteres por registro: seções maiores são divididas por parágrafo
MIN_TEXTO = 40     # trechos menores que isto são ignorados
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

CAMPOS = {
    "pergunta": re.compile(r"^\s*pergunta\s*[:：]\s*(.+)$", re.I | re.M),
    "tags": re.compile(r"^\s*palavras?[- ]chave\s*[:：]\s*(.+)$", re.I | re.M),
    "origem": re.compile(r"^\s*origem\s*[:：]\s*(.+)$", re.I | re.M),
}
PROBLEMA_SOLUCAO = re.compile(r"problema\s*[:：]\s*(.+?)\s*solu[cç][aã]o\s*[:：]\s*(.+)", re.I | re.S)


def limpar(s: str) -> str:
    """Tira marcas de Markdown que atrapalham a leitura e normaliza espaços."""
    s = re.sub(r"[*_`]{1,3}", "", s)
    s = re.sub(r"^\s*[-•]\s+", "", s, flags=re.M)
    return re.sub(r"[ \t]+", " ", s).strip()


# ---------- leitura: cada formato devolve blocos (titulo?, texto) ----------

def blocos_markdown(texto: str) -> list[tuple[bool, str]]:
    saida: list[tuple[bool, str]] = []
    paragrafo: list[str] = []

    def fechar() -> None:
        if paragrafo:
            saida.append((False, "\n".join(paragrafo).strip()))
            paragrafo.clear()

    for linha in texto.splitlines():
        titulo = re.match(r"^\s{0,3}#{1,6}\s+(.*?)\s*#*\s*$", linha)
        if titulo:
            fechar()
            saida.append((True, titulo[1]))
        elif not linha.strip():
            fechar()
        else:
            paragrafo.append(linha)
    fechar()
    return saida


def blocos_docx(caminho: Path) -> list[tuple[bool, str]]:
    with zipfile.ZipFile(caminho) as z:
        raiz = ET.fromstring(z.read("word/document.xml"))
    saida = []
    for p in raiz.iter(f"{W}p"):
        texto = "".join(t.text or "" for t in p.iter(f"{W}t")).strip()
        if not texto:
            continue
        estilo = p.find(f"{W}pPr/{W}pStyle")
        nome = (estilo.get(f"{W}val") if estilo is not None else "") or ""
        saida.append((bool(re.match(r"(?i)^(heading|t[ií]tulo|ttulo)\d", nome)), texto))
    return saida


def blocos_pdf(caminho: Path) -> list[tuple[bool, str]]:
    try:
        from pypdf import PdfReader
    except ImportError:
        raise RuntimeError("para ler PDF instale o pypdf: pip install pypdf") from None
    texto = "\n".join((pag.extract_text() or "") for pag in PdfReader(str(caminho)).pages)
    return [(False, p.strip()) for p in re.split(r"\n\s*\n", texto) if p.strip()]


def ler(caminho: Path) -> list[tuple[bool, str]]:
    ext = caminho.suffix.lower()
    if ext in (".md", ".markdown"):
        return blocos_markdown(caminho.read_text(encoding="utf-8-sig"))
    if ext == ".txt":
        blocos = [p.strip() for p in re.split(r"\n\s*\n", caminho.read_text(encoding="utf-8-sig")) if p.strip()]
        # A primeira linha de um bloco, se for curta e sem pontuação final, é o título do que vem abaixo.
        saida: list[tuple[bool, str]] = []
        for bloco in blocos:
            primeira, _, resto = bloco.partition("\n")
            if len(primeira) <= 80 and not primeira.rstrip().endswith((".", "!", "?", ":", ";", ",")):
                saida.append((True, primeira.strip()))
                if resto.strip():
                    saida.append((False, resto.strip()))
            else:
                saida.append((False, bloco))
        return saida
    if ext == ".docx":
        return blocos_docx(caminho)
    if ext == ".pdf":
        return blocos_pdf(caminho)
    raise RuntimeError(f"formato não suportado: {ext}")


# ---------- blocos -> registros ----------

def primeira_frase(texto: str, limite: int = 70) -> str:
    frase = re.split(r"(?<=[.!?])\s", limpar(texto), maxsplit=1)[0]
    return frase if len(frase) <= limite else frase[: limite - 1].rstrip() + "…"


def dividir(texto: str) -> list[str]:
    """Divide uma seção longa em partes de até MAX_TEXTO caracteres, sempre entre parágrafos."""
    partes, atual = [], ""
    for p in re.split(r"\n\s*\n|\n(?=[-•*] )", texto):
        if atual and len(atual) + len(p) > MAX_TEXTO:
            partes.append(atual.strip())
            atual = ""
        atual += p + "\n\n"
    if atual.strip():
        partes.append(atual.strip())
    return partes or [texto]


def montar(arquivo: Path, titulo: str | None, texto: str, criado: str) -> list[dict]:
    campos = {}
    for nome, rx in CAMPOS.items():
        achado = rx.search(texto)
        if achado:
            campos[nome] = limpar(achado[1])
            texto = rx.sub("", texto)
    registros = []
    partes = dividir(texto.strip())
    for i, parte in enumerate(partes, 1):
        corpo = limpar(parte)
        if len(corpo) < MIN_TEXTO:
            continue
        nome = titulo or primeira_frase(corpo)
        if not titulo and not nome.endswith("…") and corpo.startswith(nome):
            resto = corpo[len(nome):].strip()  # a primeira frase virou título: não repetir no corpo
            if len(resto) >= MIN_TEXTO:
                corpo = resto
            nome = nome.rstrip(".")
        if len(partes) > 1:
            nome = f"{nome} (parte {i})"
        reg = {
            "id": "kb-" + hashlib.sha1(f"{arquivo.name}|{nome}|{corpo}".encode()).hexdigest()[:8],
            "titulo": nome,
            "texto": corpo,
            "origem": campos.get("origem") or arquivo.name,
            "arquivo": arquivo.name,
            "criado": criado,
        }
        ps = PROBLEMA_SOLUCAO.search(corpo)
        if ps:
            reg["problema"], reg["solucao"] = limpar(ps[1]), limpar(ps[2])
        if campos.get("tags"):
            reg["tags"] = campos["tags"]
        if campos.get("pergunta") and i == 1:
            reg["pergunta"] = campos["pergunta"]
        registros.append(reg)
    return registros


def registros_do_arquivo(arquivo: Path) -> list[dict]:
    criado = datetime.fromtimestamp(arquivo.stat().st_mtime).date().isoformat()
    if arquivo.suffix.lower() == ".json":
        dados = json.loads(arquivo.read_text(encoding="utf-8-sig"))
        itens = dados if isinstance(dados, list) else []
        saida = []
        for x in itens:
            if not isinstance(x, dict) or not isinstance(x.get("titulo"), str):
                continue
            texto = x.get("texto") or " ".join(filter(None, [x.get("problema"), x.get("solucao")]))
            if isinstance(texto, str) and texto.strip():
                saida.append({**{k: v for k, v in x.items() if isinstance(v, str)}, "texto": texto.strip(),
                              "origem": x.get("origem") or arquivo.name, "arquivo": arquivo.name, "criado": x.get("criado") or criado,
                              "id": x.get("id") or "kb-" + hashlib.sha1(f"{arquivo.name}|{x['titulo']}".encode()).hexdigest()[:8]})
        return saida

    registros: list[dict] = []
    titulo: str | None = None
    acumulado: list[str] = []

    def fechar() -> None:
        if acumulado:
            registros.extend(montar(arquivo, titulo, "\n\n".join(acumulado), criado))
            acumulado.clear()

    for e_titulo, texto in ler(arquivo):
        if e_titulo:
            fechar()
            titulo = limpar(texto)
        else:
            acumulado.append(texto)
    fechar()
    return registros


def main() -> int:
    ap = argparse.ArgumentParser(description="Gera a base de conhecimento a partir de documentos.")
    ap.add_argument("pasta", nargs="?", default=str(AQUI / "conhecimento"), help="pasta com os documentos")
    ap.add_argument("--saida", default=str(AQUI), help="pasta onde gravar conhecimento.json e conhecimento.js")
    args = ap.parse_args()

    pasta, saida = Path(args.pasta), Path(args.saida)
    if not pasta.is_dir():
        print(f"Pasta não encontrada: {pasta}", file=sys.stderr)
        return 1

    todos: list[dict] = []
    vistos: set[str] = set()
    for arquivo in sorted(p for p in pasta.iterdir() if p.is_file() and not p.name.startswith(("~", "."))):
        if arquivo.suffix.lower() not in {".md", ".markdown", ".txt", ".docx", ".pdf", ".json"}:
            print(f"  ignorado   {arquivo.name} (formato não suportado)")
            continue
        try:
            regs = registros_do_arquivo(arquivo)
        except Exception as erro:  # noqa: BLE001 - um arquivo ruim não pode derrubar os outros
            print(f"  ERRO       {arquivo.name}: {erro}")
            continue
        novos = [r for r in regs if r["id"] not in vistos]
        vistos.update(r["id"] for r in novos)
        todos.extend(novos)
        print(f"  {len(novos):>3} registros  {arquivo.name}")

    saida.mkdir(parents=True, exist_ok=True)
    texto_json = json.dumps(todos, ensure_ascii=False, indent=2)
    (saida / "conhecimento.json").write_text(texto_json + "\n", encoding="utf-8")
    (saida / "conhecimento.js").write_text(
        f"/* Gerado por gerar_conhecimento.py em {date.today().isoformat()}. Não edite à mão. */\n"
        f"window.BASE_CONHECIMENTO = {texto_json};\n", encoding="utf-8")
    print(f"\n{len(todos)} registros gravados em {saida / 'conhecimento.js'}")
    if not todos:
        print("Nenhum registro: confira se há documentos na pasta e se eles têm texto.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
