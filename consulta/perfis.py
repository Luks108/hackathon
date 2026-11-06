"""Perfis de acesso: quais entes e que tipo de dado cada plano enxerga.

O perfil nunca é um argumento de tool. Ele entra no ambiente do servidor MCP, fora do alcance do
modelo. Quem sobe o agente (worker, sessão do WhatsApp, testes) usa este módulo para montar esse ambiente.

    python consulta/perfis.py                    lista os perfis
    python consulta/perfis.py estado             variáveis de ambiente do perfil
    python consulta/perfis.py estado --config    configuração MCP pronta para o agente

Regra de ouro: uma sessão do agente carrega UM servidor `transparencia`, com UM perfil. Dois servidores
na mesma sessão deixariam o modelo escolher o mais permissivo.
"""

import json
import sys
from pathlib import Path

ARQUIVO = Path(__file__).with_name("perfis.json")
SERVIDOR = Path(__file__).with_name("mcp_transparencia.py")


def carregar() -> dict[str, dict]:
    perfis = json.loads(ARQUIVO.read_text(encoding="utf-8"))
    for nome, p in perfis.items():
        tenants = p.get("tenants")
        if not isinstance(tenants, list) or not tenants or not all(isinstance(t, str) and t for t in tenants):
            raise ValueError(f"perfil '{nome}': 'tenants' precisa ser uma lista não vazia de textos")
        if not isinstance(p.get("ver_pessoal"), bool):
            raise ValueError(f"perfil '{nome}': 'ver_pessoal' precisa ser true ou false")
    return perfis


def ambiente(perfil: str) -> dict[str, str]:
    """Variáveis que o servidor MCP lê. Perfil desconhecido é erro: nunca cai num perfil padrão."""
    perfis = carregar()
    if perfil not in perfis:
        raise ValueError(f"perfil desconhecido: '{perfil}'. Disponíveis: {', '.join(perfis)}")
    p = perfis[perfil]
    return {
        "TRANSPARENCIA_PERFIL": perfil,
        "TRANSPARENCIA_TENANTS": ",".join(p["tenants"]),
        "TRANSPARENCIA_VER_PESSOAL": "sim" if p["ver_pessoal"] else "nao",
    }


def config_mcp(perfil: str, python: str = sys.executable, sessao: str | None = None) -> dict:
    """Configuração para `claude --mcp-config ... --strict-mcp-config`: um único servidor, com o perfil."""
    env = ambiente(perfil)
    if sessao:
        env["TRANSPARENCIA_SESSAO"] = sessao
    return {"mcpServers": {"transparencia": {"command": python, "args": [str(SERVIDOR)], "env": env}}}


def main(argv: list[str]) -> int:
    perfis = carregar()
    if not argv:
        for nome, p in perfis.items():
            pessoal = "com dado pessoal" if p["ver_pessoal"] else "sem dado pessoal"
            print(f"{nome:16} {', '.join(p['tenants'])} ({pessoal})")
        return 0
    try:
        if "--config" in argv:
            print(json.dumps(config_mcp(argv[0]), ensure_ascii=False, indent=2))
        else:
            for k, v in ambiente(argv[0]).items():
                print(f"{k}={v}")
    except ValueError as erro:
        print(erro, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
