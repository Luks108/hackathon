"""CLI: detecta objetos numa imagem e imprime JSON (com o caminho da imagem anotada).

Uso pela sessão Claude, quando chega foto no WhatsApp:
    inferencia/.venv/bin/python inferencia/detectar.py <imagem> [--conf 0.35]
Depois: reply com files=[<anotada>] e a interpretação do Opus sobre a contagem.
"""

import argparse
import json

from yolo import detectar

p = argparse.ArgumentParser()
p.add_argument("imagem")
p.add_argument("--conf", type=float, default=0.35)
a = p.parse_args()
print(json.dumps(detectar(a.imagem, a.conf), ensure_ascii=False, indent=2))
