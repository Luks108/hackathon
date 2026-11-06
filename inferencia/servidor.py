"""Servidor de inferência no notebook (plano B e complemento do Opus).

    inferencia/.venv/bin/uvicorn servidor:app --app-dir inferencia --host 127.0.0.1 --port 8000
    cloudflared tunnel --url http://127.0.0.1:8000     → URL pública para o INFERENCIA_URL do .env

Rotas (todas exigem X-Api-Key, a mesma API_KEY do site):
    GET  /saude
    POST /detectar          multipart "imagem" → JSON com contagem, caixas e link da anotada
    GET  /anotada/{nome}    imagem com as caixas desenhadas
"""

import os
import shutil
import tempfile
from pathlib import Path

from fastapi import Depends, FastAPI, File, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse

from yolo import SAIDA, detectar, modelo


def _carregar_env() -> None:
    env = Path(__file__).resolve().parent.parent / ".env"
    for linha in env.read_text().splitlines() if env.exists() else []:
        if "=" in linha and not linha.lstrip().startswith("#"):
            k, v = linha.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


_carregar_env()
API_KEY = os.environ["API_KEY"]
app = FastAPI(title="Inferência do hackathon")


def chave(x_api_key: str = Header(default="")) -> None:
    if x_api_key != API_KEY:
        raise HTTPException(401, "chave inválida")


@app.on_event("startup")
def aquecer() -> None:
    modelo()  # exporta/carrega antes da primeira requisição


@app.get("/saude", dependencies=[Depends(chave)])
def saude() -> dict:
    return {"ok": True, "modelo": os.environ.get("MODELO", "yolo11n.pt")}


@app.post("/detectar", dependencies=[Depends(chave)])
def rota_detectar(imagem: UploadFile = File(...), conf: float = 0.35) -> dict:
    sufixo = Path(imagem.filename or "img.jpg").suffix or ".jpg"
    with tempfile.NamedTemporaryFile(suffix=sufixo, delete=False, dir=tempfile.gettempdir()) as tmp:
        shutil.copyfileobj(imagem.file, tmp)
    try:
        r = detectar(tmp.name, conf)
    finally:
        os.unlink(tmp.name)
    r["anotada"] = f"/anotada/{Path(r['anotada']).name}"
    return r


@app.get("/anotada/{nome}", dependencies=[Depends(chave)])
def anotada(nome: str) -> FileResponse:
    caminho = (SAIDA / nome).resolve()
    if caminho.parent != SAIDA.resolve() or not caminho.exists():
        raise HTTPException(404)
    return FileResponse(caminho)
