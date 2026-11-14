"""Coleta o cadastro de CNPJ da Receita Federal pela BrasilAPI (projeto aberto, licença MIT), um pedido por CNPJ.

    .venv/bin/python coleta/receita.py 10230480000130 26.852.688/0002-02
    .venv/bin/python coleta/receita.py --arquivo dados/amostra/cnpjs.txt

A BrasilAPI repassa o cadastro da Receita; não é a Receita falando. O dado vale para a data da coleta e pode estar atrasado em relação ao cadastro oficial.

- Só pede CNPJ de dígito verificador válido (não gasta pedido com número errado).
- Identificação honesta e intervalo de 3 s entre pedidos. Para no primeiro limite (429), recusa (403) ou erro do servidor: não insiste.
- Guarda só os campos listados em CAMPOS: **sócios, telefone, e-mail e endereço completo nunca são gravados** (podem ser dado de pessoa física).
- O bruto fica em BRUTO, fora do repositório: `receita-<cnpj>.json` = {fonte, url, coletado_em, resposta}. O hash desse arquivo é a âncora da prova.
"""

import json
import os
import re
import sys
import time
import urllib.error
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

URL = "https://brasilapi.com.br/api/cnpj/v1/{cnpj}"
FONTE = "Cadastro de CNPJ da Receita Federal, repassado pela BrasilAPI"
AGENTE = "hackathon-garanhuns-tech/0.1"
INTERVALO_S = 3
CAMPOS = ("cnpj", "razao_social", "nome_fantasia", "descricao_situacao_cadastral", "data_situacao_cadastral",
          "descricao_motivo_situacao_cadastral", "data_inicio_atividade", "cnae_fiscal", "cnae_fiscal_descricao",
          "natureza_juridica", "porte", "descricao_identificador_matriz_filial", "municipio", "uf", "capital_social",
          "opcao_pelo_simples", "opcao_pelo_mei")


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


def reduzir(resposta: dict, cnpj: str) -> dict:
    """Só os campos de CAMPOS. Recusa resposta que não é do CNPJ pedido (a API não pode nos entregar outro)."""
    if not isinstance(resposta, dict) or so_digitos(str(resposta.get("cnpj", ""))) != cnpj:
        raise ValueError(f"a resposta não é do CNPJ {cnpj}")
    return {c: resposta.get(c) for c in CAMPOS}


def coletar(cnpj: str, bruto: Path) -> dict:
    url = URL.format(cnpj=cnpj)
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": AGENTE, "Accept": "application/json"}), timeout=60) as r:
        resposta = json.loads(r.read(5 * 1024 * 1024))
    conteudo = {"fonte": FONTE, "url": url, "coletado_em": date.today().isoformat(), "resposta": reduzir(resposta, cnpj)}
    destino = bruto / f"receita-{cnpj}.json"
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
            c = coletar(cnpj, bruto)["resposta"]
            print(f"{cnpj}: {c['razao_social']} | {c['descricao_situacao_cadastral']}")
        except urllib.error.HTTPError as erro:
            if erro.code == 404:
                print(f"{cnpj}: não consta no cadastro")      # não é erro: o CNPJ pode nem existir
                continue
            print(f"{cnpj}: a BrasilAPI respondeu {erro.code}; parando sem insistir", file=sys.stderr)
            return 1
        except (urllib.error.URLError, ValueError, TimeoutError) as erro:
            print(f"{cnpj}: {erro}; parando", file=sys.stderr)
            return 1
    return 1 if invalidos else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
