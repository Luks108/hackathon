"""Formatação condicional da planilha de estoque (cores por Tipo / Status).

    inferencia/.venv/bin/python planilha/formatar.py

Roda uma vez e vale para a aba inteira, inclusive as linhas que o bot ainda vai acrescentar — por isso
é regra condicional, e não cor pintada célula a célula. Reexecutar é seguro: as regras antigas criadas
por este script são removidas antes (marcadas pela própria fórmula).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from mcp_planilha import planilha  # noqa: E402

VERDE = ((0.85, 0.92, 0.83), (0.22, 0.46, 0.11))
AMARELO = ((1.00, 0.95, 0.80), (0.50, 0.38, 0.00))
VERMELHO = ((0.96, 0.80, 0.80), (0.60, 0.00, 0.00))

# Aba → [(coluna, {valor na célula: (fundo, texto)})]. Tons claros: a planilha é lida no projetor.
CORES = {
    "Movimentações": [
        ("C", {"entrada": VERDE, "saída": AMARELO, "perda": VERMELHO}),
        ("H", {"whatsapp": VERDE}),
    ],
}


def _cor(rgb):
    return {"red": rgb[0], "green": rgb[1], "blue": rgb[2]}


def aplicar() -> list[str]:
    ss = planilha()
    feito = []
    for nome, colunas in CORES.items():
        sid = ss.worksheet(nome).id
        # Limpa as regras existentes desta aba (índices caem ao remover: sempre apaga a de índice 0).
        atual = ss.fetch_sheet_metadata().get("sheets", [])
        antigas = next((s.get("conditionalFormats", []) for s in atual
                        if s["properties"]["sheetId"] == sid), [])
        pedidos = [{"deleteConditionalFormatRule": {"sheetId": sid, "index": 0}} for _ in antigas]
        novas = 0  # índice da regra nova: conta só os adds, já que os deletes zeram a lista antes

        for coluna, valores in colunas:
            faixa = {"sheetId": sid, "startRowIndex": 1,
                     "startColumnIndex": ord(coluna) - 65, "endColumnIndex": ord(coluna) - 64}
            for valor, (fundo, texto) in valores.items():
                pedidos.append({"addConditionalFormatRule": {"index": novas, "rule": {
                    "ranges": [faixa],
                    "booleanRule": {
                        "condition": {"type": "TEXT_EQ", "values": [{"userEnteredValue": valor}]},
                        "format": {"backgroundColor": _cor(fundo),
                                   "textFormat": {"foregroundColor": _cor(texto), "bold": True}},
                    },
                }}})
                novas += 1
            feito.append(f"{nome}!{coluna}: " + ", ".join(valores))
        ss.batch_update({"requests": pedidos})
    return feito


if __name__ == "__main__":
    print("\n".join(aplicar()))
