"""Servidor MCP `visao`: o YOLO fica carregado na memória enquanto a sessão Claude estiver aberta.

O CLI (detectar.py) gasta ~5 s por chamada só importando o PyTorch; aqui a detecção custa ~50 ms.
Declarado no .mcp.json da raiz. Tools: detectar, trocar_modelo, status_visao.
"""

import os
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def stdout_no_stderr():
    """O stdout é o canal do protocolo MCP: qualquer print do Ultralytics/OpenVINO (inclusive vindo de C)
    durante um export corromperia a conversa. Desvia o fd 1 para o stderr enquanto isso roda.
    Só usar dentro de uma tool (a resposta sai depois que ela retorna), nunca em paralelo ao transporte."""
    sys.stdout.flush()
    salvo = os.dup(1)
    os.dup2(2, 1)
    try:
        yield
    finally:
        sys.stdout.flush()
        os.dup2(salvo, 1)
        os.close(salvo)


with stdout_no_stderr():
    import cv2
    import zxingcpp

    import nfce
    import yolo

from mcp.server.mcpserver import MCPServer  # noqa: E402

mcp = MCPServer(
    name="visao",
    instructions=(
        "YOLO local (CPU, OpenVINO) para detecção de objetos com caixas e contagem. "
        "Complementa a visão do próprio modelo: use quando precisar de contagem exata, coordenadas "
        "ou de uma imagem anotada para devolver ao usuário (passe `anotada` em files no reply do WhatsApp). "
        "Classes do modelo padrão: as 80 do COCO (pessoa, carro, celular, garrafa, etc.)."
    ),
)

_pronto = threading.Event()
_erro_carga: str | None = None


def _aquecer() -> None:
    global _erro_carga
    # Sem desviar o stdout: isto roda em paralelo ao handshake, e a resposta do initialize se perderia.
    # Carregar um modelo já exportado não imprime nada (YOLO_VERBOSE=False). O export do primeiro uso
    # é feito antes, por `detectar.py` ou `trocar_modelo`.
    try:
        yolo.modelo()
    except Exception as e:  # noqa: BLE001
        _erro_carga = str(e)
    _pronto.set()


# Carrega em segundo plano: o handshake MCP responde na hora e o modelo fica pronto em poucos segundos.
threading.Thread(target=_aquecer, daemon=True).start()


@mcp.tool()
def detectar(image_path: str, confianca: float = 0.35, classes: list[str] | None = None) -> dict:
    """Detecta objetos numa imagem local. Retorna contagem por classe, caixas [x1,y1,x2,y2] em pixels,
    tempo em ms e `anotada` (caminho da imagem com as caixas desenhadas).
    `classes` filtra o resultado (ex.: ["person", "car"])."""
    if not Path(image_path).is_file():
        raise ValueError(f"imagem não encontrada: {image_path}")
    _pronto.wait(timeout=120)
    if _erro_carga:
        raise RuntimeError(f"modelo não carregou: {_erro_carga}")
    r = yolo.detectar(image_path, confianca)
    if classes:
        r["deteccoes"] = [d for d in r["deteccoes"] if d["classe"] in classes]
        r["contagem"] = {c: n for c, n in r["contagem"].items() if c in classes}
    return r


@mcp.tool()
def trocar_modelo(modelo: str) -> dict:
    """Troca o modelo YOLO em uso. Aceita um nome oficial (yolo11n.pt rápido, yolo11s.pt mais preciso,
    yolo11m.pt ainda mais preciso e lento; yolo11n-seg.pt segmentação; yolo11n-pose.pt pose) — baixado e
    exportado na primeira vez — ou o caminho absoluto de um .pt treinado no dia."""
    _pronto.wait(timeout=120)
    inicio = time.time()
    with stdout_no_stderr():
        yolo.trocar(modelo)
    return {"modelo": yolo.MODELO, "carregado_em_s": round(time.time() - inicio, 1)}


@mcp.tool()
def ler_codigos(image_path: str) -> list[dict]:
    """Lê QR codes e códigos de barras (EAN-13, Code128…) numa foto. Use para o QR da nota fiscal ou o código
    de barras de um produto — o modelo de visão não lê o conteúdo de um QR com confiança."""
    if not Path(image_path).is_file():
        raise ValueError(f"imagem não encontrada: {image_path}")
    img = cv2.imread(image_path)
    return [{"formato": c.format.name, "texto": c.text} for c in zxingcpp.read_barcodes(img)]


@mcp.tool()
def consultar_nfce(texto_qr_ou_chave: str) -> dict:
    """Busca na SEFAZ os itens de uma NFC-e (cupom fiscal) a partir do texto do QR ou da chave de 44 dígitos.
    Devolve loja, data, total, pagamento e itens (descrição, quantidade, unidade, valor unitário, EAN).
    Automático para PE; outros estados devolvem erro — aí leia os itens no cupom impresso pela foto."""
    return nfce.consultar(texto_qr_ou_chave)


@mcp.tool()
def nota_da_foto(image_path: str) -> dict:
    """Atalho: foto do cupom → lê o QR → consulta a SEFAZ → itens da nota. Se não achar o QR, devolve erro e
    você pode pedir outra foto (QR inteiro, sem reflexo) ou ler a chave de 44 dígitos impressa no cupom."""
    qrs = [c for c in ler_codigos(image_path) if c["formato"] == "QRCode" and nfce.chave_de(c["texto"])]
    if not qrs:
        return {"erro": "não encontrei o QR da nota na foto"}
    return nfce.consultar(qrs[0]["texto"])


@mcp.tool()
def status_visao() -> dict:
    """Modelo em uso, se já está carregado e quais classes ele conhece."""
    pronto = _pronto.is_set() and not _erro_carga
    return {
        "modelo": yolo.MODELO,
        "pronto": pronto,
        "erro": _erro_carga,
        "classes": list(yolo.modelo().names.values()) if pronto else None,
    }


if __name__ == "__main__":
    mcp.run("stdio")
