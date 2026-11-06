"""Apoio dos testes: carrega o servidor MCP com um perfil e, quando preciso, troca o banco por um falso."""

import importlib
import os
import sys
import tempfile
from pathlib import Path

CONSULTA = Path(__file__).resolve().parents[1]
RAIZ = CONSULTA.parent
sys.path.insert(0, str(CONSULTA))

import logging

import perfis  # noqa: E402

logging.getLogger("neo4j.notifications").setLevel(logging.ERROR)  # propriedade nula não existe no banco de exemplo

VARIAVEIS = ("TRANSPARENCIA_PERFIL", "TRANSPARENCIA_TENANTS", "TRANSPARENCIA_VER_PESSOAL",
             "TRANSPARENCIA_LOG", "TRANSPARENCIA_SESSAO", "BRUTO")


def carregar_servidor(perfil: str | None = None, ambiente: dict | None = None, log: Path | None = None):
    """Importa mcp_transparencia do zero, com o ambiente do perfil, como o worker faria ao subir o agente."""
    for k in VARIAVEIS:
        os.environ.pop(k, None)
    if perfil:
        os.environ.update(perfis.ambiente(perfil))
    # Teste nunca grava no registro de verdade do projeto (logs/consultas.jsonl).
    os.environ["TRANSPARENCIA_LOG"] = str(log or Path(tempfile.gettempdir()) / "transparencia-testes.jsonl")
    os.environ.update(ambiente or {})
    sys.modules.pop("mcp_transparencia", None)
    return importlib.import_module("mcp_transparencia")


def trocar_banco(mod, resposta=None):
    """Fecha a conexão real (aberta ao importar) e instala o banco falso."""
    mod.driver.close()
    mod.driver = DriverFalso(resposta)
    return mod


class SessaoFalsa:
    def __init__(self, chamadas, resposta):
        self.chamadas, self.resposta = chamadas, resposta

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def run(self, cypher, **parametros):
        self.chamadas.append((cypher, parametros))
        return iter(self.resposta)


class DriverFalso:
    """Registra cada consulta que chegaria ao Neo4j, sem conectar a nada."""

    def __init__(self, resposta=None):
        self.chamadas: list[tuple[str, dict]] = []
        self.resposta = resposta if resposta is not None else []

    def session(self):
        return SessaoFalsa(self.chamadas, self.resposta)
