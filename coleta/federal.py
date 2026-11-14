"""Coleta o CEIS e o CNEP (sanções federais) em arquivo, do Portal da Transparência. Não precisa de chave.

    .venv/bin/python coleta/federal.py            # CEIS e CNEP
    .venv/bin/python coleta/federal.py ceis

Um pedido para a página de cada cadastro (para achar a data do arquivo mais recente) e um para o arquivo, com
identificação honesta. Se o portal responder outra coisa que não o arquivo (por exemplo, um desafio anti-robô), para:
não contornamos. O bruto fica em BRUTO, fora do repositório, e o CSV de pessoa física traz o CPF completo.

Grava `federal-<cadastro>.csv` (o arquivo do portal, sem alterar) e `federal-<cadastro>.meta.json` (data do arquivo,
quando foi baixado, endereço e hash). A extração (`extrair.py`) lê os dois.
"""

import hashlib
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
import zipfile
from datetime import date
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
_ENV = RAIZ / ".env"
for linha in (_ENV.read_text(encoding="utf-8-sig").splitlines() if _ENV.exists() else []):   # mesmo critério dos outros leitores do .env
    if "=" in linha and not linha.lstrip().startswith("#"):
        k, v = linha.split("=", 1)
        if k.strip() and v.strip():      # valor vazio não vira variável
            os.environ.setdefault(k.strip(), v.strip())

CADASTROS = ("ceis", "cnep")
PAGINA = "https://portaldatransparencia.gov.br/download-de-dados/{cadastro}"
ARQUIVO = "https://portaldatransparencia.gov.br/download-de-dados/{cadastro}/{data}"
AGENTE = "hackathon-garanhuns-tech/0.1"
INTERVALO_S = 5
LIMITE_BYTES = 100 * 1024 * 1024          # o CEIS de 13/11/2026 tem 3,5 MB compactado; mais de 100 MB é outra coisa


def data_mais_recente(html: str, cadastro: str) -> str:
    """A página lista os arquivos disponíveis em `arquivos.push({"ano" : "2026", "mes" : "11", "dia" : "13", "origem" : "CEIS"})`."""
    datas = []
    for m in re.finditer(r'arquivos\.push\(\{\s*"ano"\s*:\s*"(\d{4})"\s*,\s*"mes"\s*:\s*"(\d{1,2})"\s*,\s*"dia"\s*:\s*"(\d{1,2})"\s*,\s*"origem"\s*:\s*"([^"]+)"', html):
        if m[4].lower() == cadastro.lower():
            datas.append(f"{m[1]}{int(m[2]):02d}{int(m[3]):02d}")
    if not datas:
        raise ValueError(f"a página do {cadastro.upper()} não lista nenhum arquivo (o portal mudou ou respondeu outra coisa)")
    return max(datas)


def csv_do_zip(conteudo: bytes) -> bytes:
    """Devolve o único CSV do zip. Qualquer outra coisa (página de desafio, erro em HTML) é recusada."""
    if not conteudo.startswith(b"PK"):
        raise ValueError("o portal não devolveu um arquivo zip (provável desafio anti-robô ou erro); não insisto nem contorno")
    with zipfile.ZipFile(io.BytesIO(conteudo)) as z:
        nomes = [n for n in z.namelist() if n.lower().endswith(".csv")]
        if len(nomes) != 1:
            raise ValueError(f"esperava um CSV no zip, achei {len(nomes)}")
        return z.read(nomes[0])


def _baixar(url: str) -> bytes:
    pedido = urllib.request.Request(url, headers={"User-Agent": AGENTE})
    with urllib.request.urlopen(pedido, timeout=120) as r:
        corpo = r.read(LIMITE_BYTES + 1)
    if len(corpo) > LIMITE_BYTES:
        raise ValueError("arquivo maior que o esperado; parando")
    return corpo


def coletar(cadastro: str, bruto: Path) -> dict:
    pagina = _baixar(PAGINA.format(cadastro=cadastro)).decode("utf-8", errors="replace")
    data = data_mais_recente(pagina, cadastro)
    time.sleep(INTERVALO_S)
    url = ARQUIVO.format(cadastro=cadastro, data=data)
    conteudo = csv_do_zip(_baixar(url))
    destino = bruto / f"federal-{cadastro}.csv"
    destino.write_bytes(conteudo)
    destino.chmod(0o600)
    meta = {"cadastro": cadastro.upper(), "data_do_arquivo": f"{data[:4]}-{data[4:6]}-{data[6:]}", "coletado_em": date.today().isoformat(),
            "url": url, "sha256": hashlib.sha256(conteudo).hexdigest(), "bytes": len(conteudo)}
    (bruto / f"federal-{cadastro}.meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return meta


def main(argv: list[str]) -> int:
    pedidos = [a.lower() for a in argv] or list(CADASTROS)
    if any(p not in CADASTROS for p in pedidos):
        print(f"cadastros válidos: {', '.join(CADASTROS)}", file=sys.stderr)
        return 1
    if "BRUTO" not in os.environ:
        print("Defina BRUTO no .env (modelo em .env.exemplo).", file=sys.stderr)
        return 1
    bruto = Path(os.environ["BRUTO"])
    bruto.mkdir(parents=True, exist_ok=True)
    for i, cadastro in enumerate(pedidos):
        if i:
            time.sleep(INTERVALO_S)
        try:
            print(json.dumps(coletar(cadastro, bruto), ensure_ascii=False))
        except (ValueError, urllib.error.URLError) as erro:
            print(f"{cadastro.upper()}: {erro}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
