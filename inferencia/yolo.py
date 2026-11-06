"""Detector YOLO compartilhado pelo servidor HTTP e pelo CLI.

Roda na CPU: a MX110 do notebook é antiga demais para o PyTorch atual. O modelo é exportado uma vez
para OpenVINO, que no Intel de 8ª geração fica 2–3× mais rápido que o PyTorch puro.
Troque o modelo com MODELO=yolo11s.pt (mais preciso, mais lento) ou um .pt treinado no dia.
"""

import os
from pathlib import Path

os.environ.setdefault("YOLO_VERBOSE", "False")  # o CLI imprime JSON puro no stdout
from ultralytics import YOLO  # noqa: E402

AQUI = Path(__file__).parent
MODELOS = AQUI / "modelos"
SAIDA = AQUI / "saida"
MODELO = os.environ.get("MODELO", "yolo11n.pt")

_carregados: dict[str, YOLO] = {}


def modelo(nome: str | None = None) -> YOLO:
    """Carrega (e na primeira vez baixa e exporta para OpenVINO) o modelo pedido; o padrão é o atual."""
    nome = nome or MODELO
    if nome in _carregados:
        return _carregados[nome]
    MODELOS.mkdir(exist_ok=True)
    pt = Path(nome) if Path(nome).is_absolute() else MODELOS / nome
    ov = pt.parent / f"{pt.stem}_openvino_model"
    if not ov.exists():
        # Baixa o peso oficial na primeira vez; o export grava a pasta _openvino_model ao lado do .pt.
        YOLO(str(pt)).export(format="openvino", imgsz=640, half=False)
    _carregados[nome] = YOLO(str(ov), task="detect")
    return _carregados[nome]


def trocar(nome: str) -> None:
    global MODELO
    modelo(nome)
    MODELO = nome


def detectar(caminho: str, confianca: float = 0.35, anotar: bool = True) -> dict:
    r = modelo().predict(caminho, conf=confianca, imgsz=640, verbose=False)[0]
    deteccoes = [
        {
            "classe": r.names[int(c)],
            "confianca": round(float(p), 3),
            "caixa": [round(float(v)) for v in xyxy],  # x1, y1, x2, y2 em pixels
        }
        for c, p, xyxy in zip(r.boxes.cls, r.boxes.conf, r.boxes.xyxy)
    ]
    contagem: dict[str, int] = {}
    for d in deteccoes:
        contagem[d["classe"]] = contagem.get(d["classe"], 0) + 1

    resultado = {
        "modelo": MODELO,
        "tamanho": list(r.orig_shape[::-1]),  # largura, altura
        "contagem": contagem,
        "deteccoes": deteccoes,
        "ms": round(sum(r.speed.values())),
    }
    if anotar:
        SAIDA.mkdir(exist_ok=True)
        destino = SAIDA / f"{Path(caminho).stem}-anotada.jpg"
        r.save(filename=str(destino))
        resultado["anotada"] = str(destino)
    return resultado
