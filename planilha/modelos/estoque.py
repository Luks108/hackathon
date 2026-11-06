"""Modelo de abas para o desafio "estoque pelo WhatsApp". Aplica na planilha do .env (PLANILHA).

    inferencia/.venv/bin/python planilha/modelos/estoque.py            # cria as abas que faltam
    inferencia/.venv/bin/python planilha/modelos/estoque.py --recriar  # apaga e recria as abas do modelo
    inferencia/.venv/bin/python planilha/modelos/estoque.py --exemplo  # + produtos e movimentos de exemplo

Desenho (append-only):
    Movimentações  → o bot só ACRESCENTA linhas (entrada, saída, perda, ajuste).
    Produtos       → cadastro (A–D) + colunas calculadas (E–H) por fórmulas de matriz.
    Lista de compras / Preços → só fórmulas (QUERY), nunca escritas.
A planilha está em pt_BR: separador de argumentos é ";" (nomes de função em inglês funcionam).
"""

import argparse
import sys
from pathlib import Path

import gspread
from gspread.utils import ValueInputOption

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ / "planilha"))
from mcp_planilha import planilha  # noqa: E402

M = "'Movimentações'"
U = ValueInputOption.user_entered

MOVIMENTACOES = ["Data", "Produto", "Tipo", "Quantidade", "Unidade", "Preço unit.", "Loja", "Origem", "Quem", "Obs"]
TIPOS = ["entrada", "saída", "perda", "ajuste"]

PRODUTOS = ["Produto", "Unidade", "Categoria", "Estoque mínimo", "Saldo", "Consumo/dia", "Dias restantes", "Status"]
# Uma fórmula por coluna calculada, na linha 2, que se estende sozinha para todo produto cadastrado.
SOMA = lambda tipo: f'SUMIFS({M}!D:D; {M}!B:B; p; {M}!C:C; "{tipo}")'  # noqa: E731
FORMULAS_PRODUTOS = {
    "E2": f'=BYROW(A2:A; LAMBDA(p; IF(p="";; {SOMA("entrada")} + {SOMA("ajuste")} - {SOMA("saída")} - {SOMA("perda")})))',
    # Consumo médio: saídas dos últimos 30 dias ÷ dias de histórico (mín. 1, máx. 30) — não subestima no começo.
    "F2": (
        f'=BYROW(A2:A; LAMBDA(p; IF(p="";; ROUND('
        f'SUMIFS({M}!D:D; {M}!B:B; p; {M}!C:C; "saída"; {M}!A:A; ">="&(TODAY()-30))'
        f' / MAX(1; MIN(30; TODAY() - INT(IFERROR(MINIFS({M}!A:A; {M}!B:B; p); TODAY())))); 2))))'
    ),
    "G2": '=MAP(E2:E; F2:F; LAMBDA(s; c; IF(N(c)>0; ROUND(s/c; 0); "")))',
    "H2": (
        '=MAP(A2:A; D2:D; E2:E; G2:G; LAMBDA(p; m; s; d; IF(p="";; '
        'IF(s<=0; "ACABOU"; IF(s<=m; "COMPRAR"; IF(AND(d<>""; d<=5); "ACABANDO"; "ok"))))))'
    ),
}

LISTA = (
    "=QUERY(Produtos!A1:H; \"select A, B, E, D, D*2-E where H = 'ACABOU' or H = 'COMPRAR' or H = 'ACABANDO' "
    "order by E asc label E 'Tem', D 'Mínimo', D*2-E 'Sugestão de compra'\"; 1)"
)
PRECOS = (
    f"=QUERY({M}!A1:J; \"select B, G, min(F), max(F), count(F) where C = 'entrada' and F is not null "
    "group by B, G order by B, min(F) label G 'Loja', min(F) 'Menor preço', max(F) 'Maior preço', count(F) 'Compras'\"; 1)"
)

EXEMPLO_PRODUTOS = [
    ["Ovos", "un", "Mercearia", 12], ["Café", "pct 500g", "Mercearia", 1], ["Arroz", "kg", "Grãos", 2],
    ["Feijão", "kg", "Grãos", 1], ["Leite integral", "L", "Laticínios", 4], ["Açúcar", "kg", "Mercearia", 1],
]
EXEMPLO_MOVIMENTOS = [
    ["=NOW()-6", "Ovos", "entrada", 30, "un", 0.6, "Atacadão Garanhuns", "exemplo", "Lucas", ""],
    ["=NOW()-6", "Café", "entrada", 2, "pct 500g", 18.9, "Atacadão Garanhuns", "exemplo", "Lucas", ""],
    ["=NOW()-6", "Arroz", "entrada", 5, "kg", 5.49, "Atacadão Garanhuns", "exemplo", "Lucas", ""],
    ["=NOW()-6", "Leite integral", "entrada", 6, "L", 4.79, "Atacadão Garanhuns", "exemplo", "Lucas", ""],
    ["=NOW()-3", "Café", "entrada", 1, "pct 500g", 21.5, "Mercadinho do Centro", "exemplo", "Lucas", ""],
    ["=NOW()-5", "Ovos", "saída", 6, "un", "", "", "exemplo", "Lucas", ""],
    ["=NOW()-2", "Ovos", "saída", 8, "un", "", "", "exemplo", "Lucas", ""],
    ["=NOW()-4", "Leite integral", "saída", 3, "L", "", "", "exemplo", "Lucas", ""],
    ["=NOW()-1", "Café", "saída", 2, "pct 500g", "", "", "exemplo", "Lucas", ""],
    ["=NOW()-1", "Leite integral", "perda", 1, "L", "", "", "exemplo", "Lucas", "venceu"],
]


def aba(p: gspread.Spreadsheet, nome: str, recriar: bool, cols: int) -> tuple[gspread.Worksheet, bool]:
    existentes = {w.title: w for w in p.worksheets()}
    if nome in existentes and not recriar:
        return existentes[nome], False
    if nome in existentes:
        if len(existentes) == 1:  # o Sheets não deixa apagar a última aba
            p.add_worksheet("_tmp", 1, 1)
        p.del_worksheet(existentes[nome])
    return p.add_worksheet(nome, rows=1000, cols=cols), True


def cabecalho(w: gspread.Worksheet, colunas: list[str]) -> None:
    w.update([colunas], "A1")
    w.format("1:1", {"textFormat": {"bold": True}, "backgroundColor": {"red": 0.88, "green": 0.95, "blue": 0.93}})
    w.freeze(rows=1)


def main() -> None:
    a = argparse.ArgumentParser()
    a.add_argument("--recriar", action="store_true")
    a.add_argument("--exemplo", action="store_true")
    args = a.parse_args()
    p = planilha()

    mov, nova = aba(p, "Movimentações", args.recriar, len(MOVIMENTACOES))
    if nova:
        cabecalho(mov, MOVIMENTACOES)
        mov.format("A2:A", {"numberFormat": {"type": "DATE_TIME", "pattern": "dd/mm/yyyy hh:mm"}})
        mov.format("F2:F", {"numberFormat": {"type": "CURRENCY", "pattern": "R$ #,##0.00"}})
        p.batch_update({"requests": [{"setDataValidation": {
            "range": {"sheetId": mov.id, "startRowIndex": 1, "startColumnIndex": 2, "endColumnIndex": 3},
            "rule": {"condition": {"type": "ONE_OF_LIST", "values": [{"userEnteredValue": t} for t in TIPOS]},
                     "strict": True, "showCustomUi": True},
        }}]})

    prod, nova = aba(p, "Produtos", args.recriar, len(PRODUTOS))
    if nova:
        cabecalho(prod, PRODUTOS)
        for celula, formula in FORMULAS_PRODUTOS.items():
            prod.update([[formula]], celula, value_input_option=U)
        prod.format("E1:H1", {"backgroundColor": {"red": 0.93, "green": 0.93, "blue": 0.93}})  # calculadas

    for nome, formula in [("Lista de compras", LISTA), ("Preços", PRECOS)]:
        w, nova = aba(p, nome, args.recriar, 6)
        if nova:
            w.update([[formula]], "A1", value_input_option=U)
            w.format("1:1", {"textFormat": {"bold": True}})
            w.freeze(rows=1)
            if nome == "Preços":
                w.format("C2:D", {"numberFormat": {"type": "CURRENCY", "pattern": "R$ #,##0.00"}})

    # Limpa a aba padrão vazia e a temporária, se sobraram.
    for w in p.worksheets():
        if w.title in ("Página1", "Sheet1", "_tmp") and not any(w.get_all_values()):
            p.del_worksheet(w)

    if args.exemplo:
        prod.append_rows(EXEMPLO_PRODUTOS, value_input_option=U, table_range="A1")
        mov.append_rows(EXEMPLO_MOVIMENTOS, value_input_option=U, table_range="A1")

    p.reorder_worksheets([p.worksheet(n) for n in ["Produtos", "Movimentações", "Lista de compras", "Preços"]])
    print("modelo de estoque aplicado:", p.url)


if __name__ == "__main__":
    main()
