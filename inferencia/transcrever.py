"""Transcreve áudio (nota de voz do WhatsApp) para texto, na CPU, com faster-whisper.

    inferencia/.venv/bin/python inferencia/transcrever.py <audio> [--modelo small]

Imprime só o texto no stdout (o canal WhatsApp lê daqui). Modelos ficam em inferencia/modelos/whisper,
então funciona offline depois do primeiro download. WHISPER_MODELO troca o padrão (base = mais rápido,
small = mais preciso; medido no notebook antes de escolher).
"""

import argparse
import os
import re
import subprocess
from pathlib import Path

import numpy as np
from faster_whisper import WhisperModel

PASTA = Path(__file__).parent / "modelos" / "whisper"
PADRAO = os.environ.get("WHISPER_MODELO", "small")

# O exemplo de preço no contexto ensina o formato "R$ 5,50" (sem ele, "cinco e cinquenta" vira "55").
# Mas, quando o áudio corta no meio do número, o Whisper COPIA o preço do exemplo. Por isso o exemplo usa
# um valor sentinela: se "R$ 7,77" aparecer na saída, foi inventado — vira marcador para perguntar.
# Medido em 01/11/2026 com notas de voz reais do Lucas (testes/audio-real-*.ogg).
CONTEXTO = "Mensagem de voz de WhatsApp em português do Brasil. Comprei 3 pacotes por R$ 7,77 cada."
SENTINELA = re.compile(r"R\$\s?7[,.]77")
NAO_ENTENDIDO = "[valor não entendido]"


def decodificar(caminho: str) -> np.ndarray:
    """Áudio → float32 mono 16 kHz via ffmpeg. O decodificador embutido do faster-whisper (PyAV) quebra
    com o PyAV 19, e não há wheel de versão antiga para este Python."""
    pcm = subprocess.run(
        ["ffmpeg", "-nostdin", "-loglevel", "error", "-i", caminho, "-f", "s16le", "-ac", "1", "-ar", "16000", "-"],
        capture_output=True, check=True,
    ).stdout
    return np.frombuffer(pcm, np.int16).astype(np.float32) / 32768.0


def transcrever(caminho: str, modelo: str = PADRAO) -> str:
    m = WhisperModel(modelo, device="cpu", compute_type="int8", download_root=str(PASTA))
    segmentos, _ = m.transcribe(
        decodificar(caminho),
        language="pt",
        beam_size=1,  # guloso: bem mais rápido na CPU, quase sem perda em frases curtas
        vad_filter=True,  # corta silêncio do começo/fim da nota de voz
        initial_prompt=CONTEXTO,
    )
    texto = " ".join(s.text.strip() for s in segmentos).strip()
    return SENTINELA.sub(NAO_ENTENDIDO, texto)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("audio")
    p.add_argument("--modelo", default=PADRAO)
    a = p.parse_args()
    print(transcrever(a.audio, a.modelo))
