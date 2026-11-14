"""Coleta os contratos FEDERAIS de um fornecedor pelo CNPJ, na API do Portal da Transparência (`/contratos/cpf-cnpj`).

    .venv/bin/python coleta/federal_contratos.py 26.852.688/0002-02 10230480000130
    .venv/bin/python coleta/federal_contratos.py --arquivo lista.txt

Precisa da chave da API em `PORTAL_TRANSPARENCIA_CHAVE` (.env); passo a passo em docs/chave-api-portal-transparencia.md. A chave nunca é impressa nem gravada.

- Só pede CNPJ de dígito verificador válido. CPF não é consultado.
- Identificação honesta, pausa entre pedidos; para no primeiro 401, 429 ou erro do servidor: não insiste.
- Guarda só os campos de CAMPOS_CONTRATO (fica de fora, por exemplo, o contato do responsável pela compra, que é nome de pessoa).
- O bruto fica em BRUTO, fora do repositório: `federal-contratos-<cnpj>.json` = {fonte, url, coletado_em, contratos}. O hash do arquivo é a âncora da prova.
"""

import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
_ENV = RAIZ / ".env"
for linha in (_ENV.read_text(encoding="utf-8-sig").splitlines() if _ENV.exists() else []):   # mesmo critério dos outros leitores do .env
    if "=" in linha and not linha.lstrip().startswith("#"):
        k, v = linha.split("=", 1)
        if k.strip() and v.strip():      # valor vazio não vira variável
            os.environ.setdefault(k.strip(), v.strip())

URL = "https://api.portaldatransparencia.gov.br/api-de-dados/contratos/cpf-cnpj"
FONTE = "Contratos do Poder Executivo Federal, API do Portal da Transparência (CGU)"
AGENTE = "hackathon-garanhuns-tech/0.1"
INTERVALO_S = 2
MAX_PAGINAS = 20                     # por CNPJ: um fornecedor com mais que isso fica incompleto, e o arquivo diz (`completo: false`)
CAMPOS_CONTRATO = ("id", "numero", "objeto", "numeroProcesso", "fundamentoLegal", "situacaoContrato", "modalidadeCompra", "dataAssinatura",
                   "dataPublicacaoDOU", "dataInicioVigencia", "dataFimVigencia", "valorInicialCompra", "valorFinalCompra")


def so_digitos(valor: str) -> str:
    return re.sub(r"\D", "", valor or "")


def cnpj_valido(d: str) -> bool:
    if len(d) != 14 or not d.isascii() or not d.isdigit() or len(set(d)) == 1:
        return False
    for n in (12, 13):
        pesos = list(range(n - 7, 1, -1)) + list(range(9, 1, -1))
        resto = sum(int(a) * b for a, b in zip(d[:n], pesos)) % 11
        if int(d[n]) != (0 if resto < 2 else 11 - resto):
            return False
    return True


def reduzir(contrato: dict, cnpj: str) -> dict:
    """Só os campos de CAMPOS_CONTRATO, mais a unidade gestora e o órgão (nome e sigla). Recusa contrato que não é do CNPJ pedido."""
    forn = contrato.get("fornecedor") or {}
    if so_digitos(str(forn.get("cnpjFormatado") or forn.get("numeroInscricaoSocial") or "")) != cnpj:
        raise ValueError(f"a resposta traz um contrato de outro fornecedor (pedi {cnpj})")
    ug = contrato.get("unidadeGestora") or {}
    maximo = ug.get("orgaoMaximo") or {}
    return {**{c: contrato.get(c) for c in CAMPOS_CONTRATO},
            "unidadeGestora": {"codigo": ug.get("codigo"), "nome": ug.get("nome"), "orgaoMaximo": {"sigla": maximo.get("sigla"), "nome": maximo.get("nome")}},
            "fornecedor": {"cnpj": cnpj, "razaoSocialReceita": forn.get("razaoSocialReceita") or forn.get("nome")}}


def chave_da_api() -> str:
    chave = os.environ.get("PORTAL_TRANSPARENCIA_CHAVE", "").strip()
    if not chave:
        raise SystemExit("Defina PORTAL_TRANSPARENCIA_CHAVE no .env (passo a passo em docs/chave-api-portal-transparencia.md).")
    return chave


def _pagina(cnpj: str, pagina: int, chave: str) -> list:
    url = f"{URL}?{urllib.parse.urlencode({'cpfCnpj': cnpj, 'pagina': pagina})}"
    pedido = urllib.request.Request(url, headers={"User-Agent": AGENTE, "Accept": "application/json", "chave-api-dados": chave})
    with urllib.request.urlopen(pedido, timeout=60) as r:
        dados = json.loads(r.read(10 * 1024 * 1024))
    if not isinstance(dados, list):
        raise ValueError("resposta inesperada (não é uma lista de contratos)")
    return dados


def coletar(cnpj: str, bruto: Path, chave: str) -> dict:
    contratos, completo = [], True
    for pagina in range(1, MAX_PAGINAS + 1):
        if pagina > 1:
            time.sleep(INTERVALO_S)
        itens = _pagina(cnpj, pagina, chave)
        if not itens:
            break
        contratos += [reduzir(c, cnpj) for c in itens]
    else:
        completo = False
    conteudo = {"fonte": FONTE, "url": f"{URL}?cpfCnpj={cnpj}", "coletado_em": date.today().isoformat(), "completo": completo, "contratos": contratos}
    destino = bruto / f"federal-contratos-{cnpj}.json"
    destino.write_text(json.dumps(conteudo, ensure_ascii=False, indent=2), encoding="utf-8")
    destino.chmod(0o600)
    return conteudo


def main(argv: list[str]) -> int:
    if "--arquivo" in argv:
        i = argv.index("--arquivo")
        argv = argv[:i] + Path(argv[i + 1]).read_text(encoding="utf-8").split() + argv[i + 2:]
    cnpjs = list(dict.fromkeys(so_digitos(a) for a in argv if a.strip()))
    if not cnpjs:
        print("informe CNPJs ou --arquivo <lista>", file=sys.stderr)
        return 1
    if "BRUTO" not in os.environ:
        print("Defina BRUTO no .env (modelo em .env.exemplo).", file=sys.stderr)
        return 1
    chave = chave_da_api()
    bruto = Path(os.environ["BRUTO"])
    bruto.mkdir(parents=True, exist_ok=True)
    invalidos = [c for c in cnpjs if not cnpj_valido(c)]
    for c in invalidos:
        print(f"{c}: CNPJ inválido, não pedi", file=sys.stderr)
    primeiro = True
    for cnpj in (c for c in cnpjs if c not in invalidos):
        if not primeiro:
            time.sleep(INTERVALO_S)
        primeiro = False
        try:
            r = coletar(cnpj, bruto, chave)
            print(f"{cnpj}: {len(r['contratos'])} contrato(s) federal(is)" + ("" if r["completo"] else f" (parei em {MAX_PAGINAS} páginas; incompleto)"))
        except urllib.error.HTTPError as erro:
            print(f"{cnpj}: a API respondeu {erro.code}{' (chave recusada)' if erro.code == 401 else ''}; parando sem insistir", file=sys.stderr)
            return 1
        except (urllib.error.URLError, ValueError, TimeoutError) as erro:
            print(f"{cnpj}: {erro}; parando", file=sys.stderr)
            return 1
    return 1 if invalidos else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
