"""Servidor MCP `planilha`: Google Sheets como banco, na conta do cliente.

Autentica com a conta de serviço (google-sa.json na raiz do projeto). O cliente só compartilha a
planilha com hackathon-bot@hackathon-513500.iam.gserviceaccount.com como Editor.

Regra de ouro (concorrência e auditoria): dados de movimento são SÓ ACRESCENTADOS (adicionar_linhas).
Saldos e listas saem de fórmulas na própria planilha — o bot nunca sobrescreve um total.
"""

import os
import time
from pathlib import Path

import gspread
from gspread.utils import ValueInputOption
from mcp.server.mcpserver import MCPServer

RAIZ = Path(__file__).resolve().parent.parent
CHAVE = os.environ.get("GOOGLE_SA", str(RAIZ / "google-sa.json"))


def _env(nome: str) -> str:
    env = RAIZ / ".env"
    for linha in env.read_text().splitlines() if env.exists() else []:
        if linha.startswith(f"{nome}="):
            return linha.split("=", 1)[1].strip()
    return os.environ.get(nome, "")


_cliente: gspread.Client | None = None
_planilha: gspread.Spreadsheet | None = None


def cliente() -> gspread.Client:
    global _cliente
    if _cliente is None:
        _cliente = gspread.service_account(filename=CHAVE)
    return _cliente


def planilha() -> gspread.Spreadsheet:
    global _planilha
    if _planilha is None:
        alvo = _env("PLANILHA")
        if not alvo:
            raise RuntimeError("nenhuma planilha aberta — use abrir_planilha(url) ou defina PLANILHA no .env")
        _planilha = _abrir(alvo)
    return _planilha


def _abrir(url_ou_id: str) -> gspread.Spreadsheet:
    c = cliente()
    return c.open_by_url(url_ou_id) if url_ou_id.startswith("http") else c.open_by_key(url_ou_id)


def _tentar(f, tentativas: int = 3):
    """A API do Sheets devolve 429/5xx de vez em quando; Wi-Fi de evento também oscila."""
    for i in range(tentativas):
        try:
            return f()
        except gspread.exceptions.APIError as e:
            if e.response.status_code not in (429, 500, 502, 503) or i == tentativas - 1:
                raise
            time.sleep(1.5 * (i + 1))


def _registros(aba: gspread.Worksheet) -> list[dict]:
    """Valores como aparecem na planilha ("2,83", "R$ 18,90", "01/11/2026 22:10"). A conversão numérica do
    gspread lê a vírgula decimal do pt_BR como separador de milhar (2,83 → 283), então fica desligada."""
    return _tentar(lambda: aba.get_all_records(default_blank="", numericise_ignore=["all"]))


def _cabecalho(aba: gspread.Worksheet) -> list[str]:
    return [c.strip() for c in _tentar(lambda: aba.row_values(1))]


mcp = MCPServer(
    name="planilha",
    instructions=(
        "Google Sheets do cliente como banco de dados. Antes de escrever, use estrutura() para ver as abas e "
        "os cabeçalhos. Movimentos (entradas, saídas, registros) entram só por adicionar_linhas — nunca edite "
        "totais, saldos ou colunas com fórmula; eles se recalculam sozinhos. Para respostas ao usuário (saldo, "
        "lista de compras), leia as abas calculadas com ler_aba. Datas no formato DD/MM/AAAA HH:MM."
    ),
)


@mcp.tool()
def abrir_planilha(url_ou_id: str) -> dict:
    """Abre (e passa a usar) uma planilha pelo link ou ID. Ela precisa estar compartilhada com a conta do bot."""
    global _planilha
    _planilha = _abrir(url_ou_id)
    return estrutura()


@mcp.tool()
def estrutura() -> dict:
    """Título, link, abas e o cabeçalho (linha 1) de cada aba da planilha em uso."""
    p = planilha()
    return {
        "titulo": p.title,
        "url": p.url,
        "abas": {a.title: {"cabecalho": _cabecalho(a), "linhas": a.row_count} for a in p.worksheets()},
    }


@mcp.tool()
def ler_aba(aba: str, limite: int = 300) -> list[dict]:
    """Lê a aba como lista de registros (chaves = cabeçalho da linha 1), já com os valores calculados das fórmulas."""
    a = planilha().worksheet(aba)
    registros = _registros(a)
    return [r for r in registros if any(str(v).strip() for v in r.values())][:limite]


@mcp.tool()
def adicionar_linhas(aba: str, linhas: list[dict]) -> dict:
    """Acrescenta linhas no fim da aba. Cada linha é um dicionário {cabeçalho: valor}; colunas ausentes ficam vazias.
    Valores são interpretados como se digitados. A planilha é pt_BR: mande números como número JSON (3, 18.9),
    nunca como texto ("1.5" pode virar data); datas como "DD/MM/AAAA HH:MM"."""
    a = planilha().worksheet(aba)
    cab = _cabecalho(a)
    desconhecidas = {k for l in linhas for k in l} - set(cab)
    if desconhecidas:
        return {"erro": f"colunas que não existem em '{aba}': {sorted(desconhecidas)}", "cabecalho": cab}
    # Escreve só até a última coluna informada: as colunas calculadas à direita (fórmulas de matriz,
    # ex.: Saldo em Produtos) quebram com #REF! se receberem qualquer valor, até string vazia.
    ultima = max(cab.index(k) for l in linhas for k in l) + 1
    valores = [[l.get(c, "") for c in cab[:ultima]] for l in linhas]
    r = _tentar(lambda: a.append_rows(valores, value_input_option=ValueInputOption.user_entered, table_range="A1"))
    return {"aba": aba, "adicionadas": len(valores), "intervalo": r.get("updates", {}).get("updatedRange")}


@mcp.tool()
def buscar(aba: str, coluna: str, contem: str) -> list[dict]:
    """Linhas cuja coluna contém o texto (sem diferenciar maiúsculas). Devolve também o número da linha."""
    a = planilha().worksheet(aba)
    registros = _registros(a)
    alvo = contem.lower()
    return [{"_linha": i + 2, **r} for i, r in enumerate(registros) if alvo in str(r.get(coluna, "")).lower()]


@mcp.tool()
def atualizar_celulas(aba: str, intervalo: str, valores: list[list]) -> dict:
    """Escreve num intervalo (ex.: "D5" ou "D5:E5"). Use só para cadastro (ex.: estoque mínimo de um produto),
    nunca para totais ou colunas com fórmula."""
    a = planilha().worksheet(aba)
    _tentar(lambda: a.update(valores, intervalo, value_input_option=ValueInputOption.user_entered))
    return {"aba": aba, "intervalo": intervalo, "ok": True}


@mcp.tool()
def criar_aba(nome: str, cabecalho: list[str]) -> dict:
    """Cria uma aba nova com o cabeçalho na linha 1 (negrito e congelado)."""
    p = planilha()
    a = _tentar(lambda: p.add_worksheet(nome, rows=1000, cols=max(len(cabecalho), 5)))
    a.update([cabecalho], "A1")
    a.format("1:1", {"textFormat": {"bold": True}})
    a.freeze(rows=1)
    return {"aba": nome, "cabecalho": cabecalho}


if __name__ == "__main__":
    mcp.run("stdio")
