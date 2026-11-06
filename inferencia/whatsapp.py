"""Manda WhatsApp a partir do Python, pela fila do gateway (sem passar pela sessão Claude).

    from whatsapp import enviar
    enviar("5587999999999", "⚠️ 2 pessoas sem capacete", arquivos=["/abs/anotada.jpg"])
"""

import json
import os
import random
import string
import time
from pathlib import Path

ESTADO = Path(os.environ.get("WHATSAPP_STATE_DIR", Path.home() / ".claude/channels/whatsapp-hackathon"))


def enviar(numero_ou_jid: str, texto: str = "", arquivos: list[str] | None = None) -> str:
    jid = numero_ou_jid if "@" in numero_ou_jid else f"{''.join(filter(str.isdigit, numero_ou_jid))}@s.whatsapp.net"
    pid = f"{int(time.time() * 1000)}-{''.join(random.choices(string.ascii_lowercase + string.digits, k=6))}"
    pedido = {"id": pid, "op": "enviar", "chat_id": jid, "texto": texto, "arquivos": arquivos or []}
    outbox = ESTADO / "outbox"
    tmp = outbox / f".{pid}.tmp"
    tmp.write_text(json.dumps(pedido, ensure_ascii=False))
    tmp.rename(outbox / f"{pid}.json")  # atômico: o gateway nunca lê pela metade
    return pid
