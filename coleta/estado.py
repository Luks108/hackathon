"""Coleta os painéis públicos do Estado de Pernambuco, com a mesma consulta que a página faz.

    .venv/bin/python coleta/estado.py contratos 2024
    .venv/bin/python coleta/estado.py execucao 2024 <arquivo com um CNPJ por linha>
    .venv/bin/python coleta/estado.py medir

Intervalo de 10 s entre pedidos e identificação honesta. Se o portal recusar, para.
O bruto fica na pasta BRUTO, fora do repositório: pode trazer CPF de contratado pessoa física.
"""

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
for linha in (RAIZ / ".env").read_text(encoding="utf-8").splitlines():
    if "=" in linha and not linha.lstrip().startswith("#"):
        k, v = linha.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

BRUTO = Path(os.environ["BRUTO"])
URL = "https://api.pentaho.transparencia.pe.gov.br/pentaho/plugin/cda/api/doQuery?"
RAIZ_CDA = "/public/OpenReports/Portal_Producao/"
CONTRATOS = RAIZ_CDA + "Painel_Contratos/Painel_Contratos_V2.cda"
FORNECEDORES = RAIZ_CDA + "Painel_Despesas_Fornecedores/Painel_Despesa_fornecedores.cda"
AGENTE = "hackathon-garanhuns-tech/0.1"
INTERVALO_S = 10
PAGINA = 200
FILTROS = dict(para_ug="0", para_situacao="", para_valor_inicial="", para_valor_final="", para_inicio_vigencia="",
               para_fim_vigencia="", para_contrato="", para_processo_licitatorio="", para_cpf_cnpj="", para_objeto="")


def consultar(caminho: str, consulta: str, **parametros) -> dict:
    corpo = {"path": caminho, "dataAccessId": consulta, "outputIndexId": "1", "pageSize": "0", "pageStart": "0",
             "sortBy": "", "paramsearchBox": ""}
    corpo.update({"param" + k: v for k, v in parametros.items()})
    pedido = urllib.request.Request(URL, data=urllib.parse.urlencode(corpo).encode(), headers={
        "User-Agent": AGENTE, "Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"})
    time.sleep(INTERVALO_S)
    with urllib.request.urlopen(pedido, timeout=90) as r:
        return json.loads(r.read())


def gravar(nome: str, dados) -> None:
    caminho = BRUTO / nome
    caminho.write_text(json.dumps(dados, ensure_ascii=False), encoding="utf-8")
    caminho.chmod(0o600)


def coletar_contratos(ano: str) -> None:
    linhas, deslocamento = [], 0
    colunas = None
    while True:
        r = consultar(CONTRATOS, "sql_tabela_principal", para_ano=ano, limit_=str(PAGINA), offset_=str(deslocamento), **FILTROS)
        colunas = colunas or [c["colName"] for c in r["metadata"]]
        linhas += r["resultset"]
        print(f"contratos {ano}: {len(linhas)}", flush=True)
        if len(r["resultset"]) < PAGINA:
            break
        deslocamento += PAGINA
    gravar(f"pe-contratos-{ano}.json", {"coletado_em": "2026-11-06", "ano": ano, "colunas": colunas, "linhas": linhas})


def medir() -> None:
    saida = {}
    for ano in range(2019, 2027):
        r = consultar(CONTRATOS, "sql_tabela_principal_count", para_ano=str(ano), **FILTROS)
        saida[str(ano)] = r["resultset"][0][0] if r["resultset"] else 0
        print(ano, saida[str(ano)], flush=True)
    gravar("pe-volumes.json", {"coletado_em": "2026-11-06", "contratos_por_ano": saida})


def coletar_execucao(ano: str, arquivo: str) -> None:
    documentos = [x.strip().lstrip("0") for x in Path(arquivo).read_text(encoding="utf-8").splitlines() if x.strip()]
    saida: dict[str, list] = {}
    for i, doc in enumerate(documentos, 1):
        r = consultar(FORNECEDORES, "select_tabela", par_ano=ano, par_ug="0", par_nm_credor=doc, limit_="200", offset_="0")
        saida[doc] = r["resultset"]
        print(f"execução {i}/{len(documentos)}: {len(r['resultset'])} linhas", flush=True)
        gravar(f"pe-execucao-{ano}.json", {"coletado_em": "2026-11-06", "ano": ano, "colunas": [c["colName"] for c in r["metadata"]], "por_documento": saida})


if __name__ == "__main__":
    try:
        {"medir": medir, "contratos": lambda: coletar_contratos(sys.argv[2]), "execucao": lambda: coletar_execucao(sys.argv[2], sys.argv[3])}[sys.argv[1]]()
    except urllib.error.HTTPError as e:
        sys.exit(f"o portal respondeu {e.code}: parando sem insistir")
