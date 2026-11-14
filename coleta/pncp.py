"""Coleta contratos de um ÓRGÃO no PNCP (Portal Nacional de Contratações Públicas), API oficial de consulta.

    .venv/bin/python coleta/pncp.py 11303906000100 --de 2026-01-01 --ate 2026-11-14

A API NÃO filtra por fornecedor: só por data de publicação (janela de no máximo 365 dias), órgão e unidade. Serve para ampliar os contratos de órgãos
que a gente escolhe, não para consultar um CNPJ qualquer. O mapa órgão -> ente do projeto está em `extrair.py` (ORGAOS_PNCP).

- Janelas de até 365 dias (a API recusa mais que isso). Página de 10: com 100 o servidor respondeu 500 em 14/11/2026.
- Identificação honesta, 4 s entre pedidos (a API leva cerca de 15 s por página), para no primeiro erro: não insiste.
- Guarda só os campos de CAMPOS (fica de fora o nome do usuário que publicou, o texto livre de informação complementar e o subcontratado).
- O bruto fica em BRUTO, fora do repositório: `pncp-<orgao>-<de>-<ate>.json` = {fonte, url, coletado_em, de, ate, total, completo, contratos}.
"""

import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
_ENV = RAIZ / ".env"
for linha in (_ENV.read_text(encoding="utf-8-sig").splitlines() if _ENV.exists() else []):   # mesmo critério dos outros leitores do .env
    if "=" in linha and not linha.lstrip().startswith("#"):
        k, v = linha.split("=", 1)
        if k.strip() and v.strip():      # valor vazio não vira variável
            os.environ.setdefault(k.strip(), v.strip())

URL = "https://pncp.gov.br/api/consulta/v1/contratos"
FONTE = "Contratos publicados no PNCP (Portal Nacional de Contratações Públicas), API de consulta"
AGENTE = "hackathon-garanhuns-tech/0.1"
INTERVALO_S = 4
TAMANHO_PAGINA = 10
JANELA_DIAS = 365
CAMPOS = ("numeroControlePNCP", "anoContrato", "sequencialContrato", "numeroContratoEmpenho", "objetoContrato", "valorInicial", "valorGlobal",
          "valorAcumulado", "dataAssinatura", "dataVigenciaInicio", "dataVigenciaFim", "dataPublicacaoPncp", "tipoPessoa", "niFornecedor",
          "nomeRazaoSocialFornecedor", "processo")


def so_digitos(valor: str) -> str:
    return re.sub(r"\D", "", valor or "")


def janelas(de: date, ate: date) -> list[tuple[date, date]]:
    """Divide [de, ate] em janelas de no máximo 365 dias (a API recusa períodos maiores)."""
    if ate < de:
        raise ValueError("a data final é anterior à inicial")
    saida, inicio = [], de
    while inicio <= ate:
        fim = min(inicio + timedelta(days=JANELA_DIAS - 1), ate)
        saida.append((inicio, fim))
        inicio = fim + timedelta(days=1)
    return saida


def reduzir(contrato: dict, orgao: str) -> dict:
    """Só os campos de CAMPOS, mais o órgão e a unidade. Recusa contrato de outro órgão."""
    entidade = contrato.get("orgaoEntidade") or {}
    if so_digitos(str(entidade.get("cnpj", ""))) != orgao:
        raise ValueError(f"a resposta traz um contrato de outro órgão (pedi {orgao})")
    unidade = contrato.get("unidadeOrgao") or {}
    return {**{c: contrato.get(c) for c in CAMPOS},
            "orgaoEntidade": {"cnpj": orgao, "razaoSocial": entidade.get("razaoSocial")},
            "unidadeOrgao": {"codigoUnidade": unidade.get("codigoUnidade"), "nomeUnidade": unidade.get("nomeUnidade"),
                             "municipioNome": unidade.get("municipioNome"), "ufSigla": unidade.get("ufSigla")}}


def _pagina(orgao: str, de: date, ate: date, pagina: int) -> dict:
    consulta = urllib.parse.urlencode({"dataInicial": de.strftime("%Y%m%d"), "dataFinal": ate.strftime("%Y%m%d"), "cnpjOrgao": orgao,
                                       "pagina": pagina, "tamanhoPagina": TAMANHO_PAGINA})
    pedido = urllib.request.Request(f"{URL}?{consulta}", headers={"User-Agent": AGENTE, "Accept": "application/json"})
    with urllib.request.urlopen(pedido, timeout=120) as r:
        dados = json.loads(r.read(20 * 1024 * 1024))
    if not isinstance(dados, dict) or not isinstance(dados.get("data"), list):
        raise ValueError("resposta inesperada (sem a lista `data`)")
    return dados


def coletar(orgao: str, de: date, ate: date, bruto: Path) -> dict:
    contratos, total, primeiro = [], 0, True
    for ini, fim in janelas(de, ate):
        pagina = 1
        while True:
            if not primeiro:
                time.sleep(INTERVALO_S)
            primeiro = False
            dados = _pagina(orgao, ini, fim, pagina)
            contratos += [reduzir(c, orgao) for c in dados["data"]]
            total += 0 if pagina > 1 else int(dados.get("totalRegistros") or 0)
            if pagina >= int(dados.get("totalPaginas") or 0) or not dados["data"]:
                break
            pagina += 1
    conteudo = {"fonte": FONTE, "url": f"{URL}?cnpjOrgao={orgao}", "coletado_em": date.today().isoformat(), "de": de.isoformat(), "ate": ate.isoformat(),
                "total": total, "completo": len(contratos) == total, "contratos": contratos}
    destino = bruto / f"pncp-{orgao}-{de:%Y%m%d}-{ate:%Y%m%d}.json"
    destino.write_text(json.dumps(conteudo, ensure_ascii=False, indent=2), encoding="utf-8")
    destino.chmod(0o600)
    return conteudo


def main(argv: list[str]) -> int:
    if not argv or argv[0].startswith("--"):
        print("uso: coleta/pncp.py <cnpj do órgão> --de AAAA-MM-DD --ate AAAA-MM-DD", file=sys.stderr)
        return 1
    orgao = so_digitos(argv[0])
    try:
        de = date.fromisoformat(argv[argv.index("--de") + 1])
        ate = date.fromisoformat(argv[argv.index("--ate") + 1]) if "--ate" in argv else date.today()
    except (ValueError, IndexError):
        print("informe --de AAAA-MM-DD (e, se quiser, --ate AAAA-MM-DD)", file=sys.stderr)
        return 1
    if len(orgao) != 14:
        print("o CNPJ do órgão precisa ter 14 dígitos", file=sys.stderr)
        return 1
    if "BRUTO" not in os.environ:
        print("Defina BRUTO no .env (modelo em .env.exemplo).", file=sys.stderr)
        return 1
    bruto = Path(os.environ["BRUTO"])
    bruto.mkdir(parents=True, exist_ok=True)
    try:
        c = coletar(orgao, de, ate, bruto)
    except (ValueError, urllib.error.URLError, TimeoutError) as erro:
        print(f"{orgao}: {erro}; parando sem insistir", file=sys.stderr)
        return 1
    print(f"{orgao}: {len(c['contratos'])} contratos de {c['de']} a {c['ate']}" + ("" if c["completo"] else f" (a API informou {c['total']}: incompleto)"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
