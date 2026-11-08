"""Confere se esta máquina está pronta para rodar o projeto. Não altera nada e nunca mostra segredos.

    python conferir_ambiente.py --preparar   # cria .env e site/hackathon-config.php com chaves novas (só se não existirem)
    python conferir_ambiente.py              # confere programas, .env e configuração
    python conferir_ambiente.py --servicos   # também confere o que deveria estar no ar (bancos, site, worker)

Cada linha começa com OK, FALTA (precisa corrigir) ou AVISO (pode seguir). A causa e o conserto aparecem logo abaixo.
Guia completo: docs/rodar-no-windows-e-no-linux.md
"""
import codecs
import importlib.util
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
falhas = 0


def linha(estado: str, texto: str, dica: str = ""):
    global falhas
    falhas += estado == "FALTA"
    print(f"{estado:6} {texto}")
    if dica and estado != "OK":
        print(f"       -> {dica}")


def versao(cmd: list[str]) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
        return (r.stdout or r.stderr).strip().splitlines()[0] if (r.stdout or r.stderr).strip() else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


def ler_env() -> dict[str, str]:
    arquivo = RAIZ / ".env"
    valores = {}
    if arquivo.exists():
        for l in arquivo.read_text(encoding="utf-8").splitlines():
            if "=" in l and not l.lstrip().startswith("#"):
                k, v = l.split("=", 1)
                valores[k.strip()] = v.strip()
    return valores


def tem_bom(arquivo: Path) -> bool:
    return arquivo.exists() and arquivo.read_bytes().startswith(codecs.BOM_UTF8)


def preparar() -> int:
    """Cria .env e site/hackathon-config.php a partir dos exemplos, com chaves novas e iguais, sem BOM e com fim de linha LF.
    Não sobrescreve nada que já exista. Serve para desenvolvimento local; na exibição o .env leva a chave do site publicado."""
    env, cfg = RAIZ / ".env", RAIZ / "site" / "hackathon-config.php"
    chave = secrets.token_urlsafe(32)
    if env.exists():
        print("já existe: .env (não alterei)")
    else:
        texto = (RAIZ / ".env.exemplo").read_text(encoding="utf-8")
        for nome, valor in (("NEO4J_SENHA", secrets.token_urlsafe(24)), ("CHAVE_PF", secrets.token_urlsafe(32)), ("WORKER_KEY", chave)):
            texto = re.sub(rf"(?m)^{nome}=.*$", f"{nome}={valor}", texto)
        env.write_bytes(texto.replace("\r\n", "\n").encode("utf-8"))
        print("criado:  .env  (senhas e chave novas; não compartilhe este arquivo)")
    if cfg.exists():
        print("já existe: site/hackathon-config.php (não alterei)")
    else:
        texto = (RAIZ / "site" / "hackathon-config.exemplo.php").read_text(encoding="utf-8")
        valor = ler_env().get("WORKER_KEY") or chave
        texto = re.sub(r"(?m)^(const WORKER_KEY = )'[^']*'", lambda m: f"{m.group(1)}'{valor}'", texto)
        cfg.write_bytes(texto.replace("\r\n", "\n").encode("utf-8"))
        print("criado:  site/hackathon-config.php  (WORKER_KEY igual à do .env)")
    print("\nPróximo passo: python conferir_ambiente.py")
    return 0


def porta_aberta(porta: int) -> bool:
    with socket.socket() as s:
        s.settimeout(1.5)
        return s.connect_ex(("127.0.0.1", porta)) == 0


def main(servicos: bool) -> int:
    print(f"Pasta do projeto: {RAIZ}\n")

    # Python e pacotes
    v = sys.version_info
    linha("OK" if v >= (3, 10) else "FALTA", f"Python {v.major}.{v.minor}.{v.micro}", "precisa ser 3.10 ou mais novo")
    em_venv = sys.prefix != getattr(sys, "base_prefix", sys.prefix)
    linha("OK" if em_venv else "AVISO", "venv ativada" if em_venv else "venv NÃO está ativada",
          "ative a venv (veja o passo 4 do guia) ou rode com .venv/bin/python (Linux) / .venv\\Scripts\\python (Windows)")
    for pacote in ("mcp", "neo4j"):
        achou = importlib.util.find_spec(pacote) is not None
        linha("OK" if achou else "FALTA", f"pacote Python '{pacote}'", "rode: pip install -r requirements.txt (com a venv ativada)")

    # Programas
    php = os.environ.get("PHP_BIN") or shutil.which("php")
    vphp = versao([php, "-v"]) if php else ""
    linha("OK" if "PHP 8.2" in vphp else ("AVISO" if vphp else "FALTA"), vphp or "PHP não encontrado",
          "o guia pede PHP 8.2 (testado só com ele). Windows: feche e reabra o terminal depois de instalar; defina PHP_BIN se preciso")
    for programa, argumento in (("git", "--version"), ("docker", "--version")):
        achado = shutil.which(programa)
        linha("OK" if achado else "FALTA", versao([achado, argumento]) if achado else f"{programa} não encontrado", "instale (veja a seção 'Antes de começar')")
    sys.path.insert(0, str(RAIZ / "chat"))
    try:
        import agente
        claude = agente.achar_claude()
        vc = versao([claude, "--version"])
        linha("OK" if vc else "FALTA", f"claude {vc}" if vc else "claude não encontrado ou não abre",
              "instale o Claude Code e entre na sua conta (veja o guia). Pode usar CLAUDE_BIN no .env")
    except Exception as e:  # noqa: BLE001
        linha("FALTA", f"não consegui carregar chat/agente.py ({type(e).__name__})", "confira se a venv tem os pacotes")
    bun = shutil.which("bun")
    if not bun and (Path.home() / ".bun" / "bin" / "bun").exists():   # o instalador do bun não mexe no PATH da sessão atual
        bun = str(Path.home() / ".bun" / "bin" / "bun")
    linha("OK" if bun else "AVISO", f"bun {versao([bun, '--version'])}" if bun else "bun não encontrado (só é preciso para o WhatsApp)",
          "o WhatsApp está pendente; instale o bun só quando for usá-lo")

    # .env
    print()
    env = ler_env()
    if not (RAIZ / ".env").exists():
        linha("FALTA", ".env não existe", "copie: cp .env.exemplo .env (Linux) / Copy-Item .env.exemplo .env (Windows)")
    if tem_bom(RAIZ / ".env"):
        linha("FALTA", ".env foi gravado com BOM (marca invisível no começo do arquivo)",
              "apague o .env e rode: python conferir_ambiente.py --preparar. Se editar à mão, salve como UTF-8 SEM BOM (no VS Code: Salvar com codificação > UTF-8)")
    for nome in ("NEO4J_SENHA", "CHAVE_PF", "NEO4J_URI", "WORKER_KEY"):
        valor = env.get(nome, "")
        if not valor:
            linha("FALTA", f".env: {nome} vazio ou ausente", "veja a tabela de variáveis do guia")
        elif valor.startswith("troque"):
            linha("FALTA", f".env: {nome} ainda tem o valor de exemplo", "troque por um valor seu (veja o guia)")
        else:
            linha("OK", f".env: {nome} preenchido")
    if env.get("WORKER_KEY") and len(env["WORKER_KEY"]) < 24:
        linha("FALTA", ".env: WORKER_KEY tem menos de 24 caracteres", "gere outra: python -c \"import secrets; print(secrets.token_urlsafe(32))\"")
    api = env.get("API_BASE", "")
    if not api:
        linha("AVISO", ".env: API_BASE ausente, então o worker apontará para o site PUBLICADO",
              "para rodar tudo local, coloque API_BASE=http://127.0.0.1:8080")
    else:
        linha("OK", f".env: API_BASE = {api}")

    # configuração do site
    cfg = RAIZ / "site" / "hackathon-config.php"
    if not cfg.exists():
        linha("FALTA", "site/hackathon-config.php não existe", "copie de site/hackathon-config.exemplo.php (passo 5 do guia)")
    else:
        if tem_bom(cfg):
            linha("FALTA", "site/hackathon-config.php foi gravado com BOM: isso quebra as respostas da API (JSON inválido)",
                  "salve como UTF-8 SEM BOM, ou apague o arquivo e rode: python conferir_ambiente.py --preparar")
        m = re.search(r"WORKER_KEY\s*=\s*'([^']*)'", cfg.read_text(encoding="utf-8-sig"))
        chave_site = m.group(1) if m else ""
        if chave_site.startswith("troque") or not chave_site:
            linha("FALTA", "site/hackathon-config.php: WORKER_KEY ainda é a de exemplo", "troque pela mesma chave do .env")
        elif env.get("WORKER_KEY") and chave_site != env["WORKER_KEY"]:
            linha("FALTA", "WORKER_KEY do .env é DIFERENTE da de site/hackathon-config.php", "o worker receberia erro 401; deixe as duas iguais")
        else:
            linha("OK", "site/hackathon-config.php existe e a WORKER_KEY confere com o .env")

    # serviços
    if servicos:
        print()
        for nome, porta, dica in (("MariaDB do site", 3307, "docker compose -f site/dev/docker-compose.yml up -d"),
                                  ("Neo4j (bolt)", 7689, "docker compose --env-file .env -f infra/docker-compose.yml up -d neo4j"),
                                  ("Site PHP", 8080, "php -S 127.0.0.1:8080 -t site/public_html site/dev/router.php")):
            linha("OK" if porta_aberta(porta) else "FALTA", f"{nome} na porta {porta}", f"suba com: {dica}")
        try:
            with urllib.request.urlopen("http://127.0.0.1:8080/api/saude", timeout=5) as r:
                linha("OK" if b'"ok":true' in r.read() else "FALTA", "site responde em /api/saude", "veja o log do PHP")
        except OSError:
            linha("FALTA", "site não respondeu em /api/saude", "suba o site (passo 8 do guia)")

    print("\nTudo pronto." if not falhas else f"\n{falhas} item(ns) para corrigir antes de seguir.")
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(preparar() if "--preparar" in sys.argv else main("--servicos" in sys.argv))
