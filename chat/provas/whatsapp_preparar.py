"""Pré-voo do WhatsApp: confere, ponto a ponto, o que precisa estar pronto antes de parear o número do bot e de testar de ponta a ponta.

    python chat/provas/whatsapp_preparar.py [--api http://127.0.0.1:8080]

SÓ LÊ. Não conecta ao WhatsApp, não chama modelo (nenhum token), não altera arquivo e NUNCA imprime número de telefone nem chave.
Saída: [OK], [AVISO] (atrapalha só parte do teste), [FALTA] (impede) e [INFO]. O código de saída é 1 se faltar algo para parear (bloco 1).
Roteiro completo: docs/whatsapp-ativacao.md.
"""
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

CHAT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CHAT))
import provedores  # noqa: E402  (carrega o .env, só leitura)

RAIZ = provedores.RAIZ
ESTADO = Path(os.environ.get("WHATSAPP_STATE_DIR") or Path.home() / ".claude" / "channels" / "whatsapp-hackathon")
CANAL = RAIZ / "canal-whatsapp"
NT = os.name == "nt"

resultados: list[tuple[str, str, str, str]] = []     # (bloco, nivel, texto, dica)
bloco_atual = ""


def bloco(nome: str):
    global bloco_atual
    bloco_atual = nome
    print(f"\n== {nome}")


def mostrar(nivel: str, texto: str, dica: str = ""):
    resultados.append((bloco_atual, nivel, texto, dica))
    print(f"[{nivel:<5}] {texto}" + (f"\n         -> {dica}" if dica and nivel in ("FALTA", "AVISO") else ""))


def rodar(cmd: list[str], limite=15) -> tuple[int, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=limite, encoding="utf-8", errors="replace")
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except (OSError, subprocess.TimeoutExpired):
        return 1, ""


def processos(padrao: str) -> list[int]:
    """PIDs de processos cuja linha de comando contém `padrao` (sem contar este próprio comando)."""
    if NT:
        filtro = f"$_.CommandLine -like '*{padrao}*' -and $_.ProcessId -ne $PID"
        cod, saida = rodar(["powershell", "-NoProfile", "-Command", f"(Get-CimInstance Win32_Process | Where-Object {{ {filtro} }}).ProcessId"])
        return [int(x) for x in saida.split() if x.isdigit()] if cod == 0 else []
    cod, saida = rodar(["pgrep", "-f", padrao])
    return [int(x) for x in saida.split() if x.isdigit() and int(x) != os.getpid()] if cod == 0 else []


def pid_vivo(pid: int) -> bool:
    # Nunca os.kill(pid, 0) no Windows: lá qualquer sinal diferente dos de console TERMINA o processo.
    if NT:
        cod, saida = rodar(["tasklist", "/FI", f"PID eq {pid}", "/NH"])
        return cod == 0 and str(pid) in saida
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def porta_aberta(host: str, porta: int) -> bool:
    try:
        with socket.create_connection((host, porta), timeout=2):
            return True
    except OSError:
        return False


def http(url: str, cabecalhos: dict | None = None, limite=5) -> tuple[int, str]:
    req = urllib.request.Request(url, headers={"User-Agent": "fornexia-preparar/1", **(cabecalhos or {})})
    try:
        with urllib.request.urlopen(req, timeout=limite) as r:
            return r.status, r.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        e.close()
        return e.code, ""
    except (OSError, ValueError):
        return 0, ""


def ler_json(caminho: Path):
    try:
        return json.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


# ------------------------------------------------------------------------------------------------------------------------
print("PRÉ-VOO DO WHATSAPP (só leitura; nenhum número de telefone nem chave é impresso)")
api_base = (sys.argv[sys.argv.index("--api") + 1] if "--api" in sys.argv else os.environ.get("API_BASE", "")).rstrip("/")

bloco("1. Para parear o número (gateway)")
bun = shutil.which("bun")
if bun:
    mostrar("OK", f"bun {rodar([bun, '--version'])[1].strip()}")
else:
    mostrar("FALTA", "bun não está instalado", "Windows: powershell -c \"irm bun.sh/install.ps1 | iex\"; Linux: curl -fsSL https://bun.sh/install | bash")
baileys = CANAL / "node_modules" / "@whiskeysockets" / "baileys"
mostrar("OK" if baileys.is_dir() else "FALTA", "dependências do gateway instaladas (Baileys)" if baileys.is_dir() else "dependências do gateway não instaladas",
        "cd canal-whatsapp && bun install")
internet, _ = http("https://raw.githubusercontent.com/wppconnect-team/wa-version/main/versions.json")
mostrar("OK" if internet == 200 else "AVISO", "consegue buscar a versão atual do WhatsApp Web" if internet == 200 else "não consegui buscar a versão do WhatsApp Web (usa a embutida)",
        "sem internet ou GitHub fora do ar; a versão embutida pode ser recusada pelo WhatsApp (erro 405)")
gateways = processos("gateway.ts")
mostrar("INFO", f"gateway rodando agora: {len(gateways)} processo(s)" if gateways else "gateway não está rodando")
if len(gateways) > 1:
    mostrar("AVISO", "mais de um processo de gateway", "só um dono por número (o gateway se recusa a subir um segundo); confira se não é o lançador + filho do mesmo")

bloco("2. Estado do gateway (pasta fora do repositório)")
mostrar("INFO", f"pasta de estado: {ESTADO}")
if RAIZ in ESTADO.resolve().parents:
    mostrar("FALTA", "a pasta de estado está DENTRO do repositório", "ela guarda a sessão do WhatsApp: mude WHATSAPP_STATE_DIR para fora do projeto")
auth = ESTADO / "auth"
n_auth = len(list(auth.iterdir())) if auth.is_dir() else 0
mostrar("INFO", "sessão salva: o número já foi pareado neste computador" if n_auth else "ainda NÃO pareado (sem sessão salva)")
status = ler_json(ESTADO / "status.json") or {}
if status:
    idade = ""
    try:
        idade = f", atualizado há {int(time.time() - time.mktime(time.strptime(status['atualizado'][:19], '%Y-%m-%dT%H:%M:%S')) - time.timezone)} s"
    except (KeyError, ValueError):
        pass
    mostrar("INFO", f"último status do gateway: conectado={bool(status.get('conectado'))}{idade}")
else:
    mostrar("INFO", "status.json não existe (o gateway nunca rodou aqui)")
acesso = ler_json(ESTADO / "access.json") or {}
liberados = acesso.get("allowFrom", [])
if liberados:
    mostrar("OK", f"números liberados no gateway: {len(liberados)} (o primeiro é o dono); grupos liberados: {len(acesso.get('allowGroups', []))}")
else:
    mostrar("AVISO", "nenhum número liberado (access.json vazio ou ausente)", "depois de parear: bun acesso.ts add <número do dono>; sem isso o gateway ignora todo mundo")

bloco("3. Para o teste ponta a ponta (worker, agente e dados)")
mostrar("OK" if (RAIZ / ".venv").is_dir() else "AVISO", "ambiente Python do projeto (.venv) existe" if (RAIZ / ".venv").is_dir() else ".venv não existe",
        "python -m venv .venv && .venv/Scripts/pip install -r requirements.txt")
try:
    import mcp  # noqa: F401
    mostrar("OK", "pacote mcp instalado (o agente precisa dele)")
except ImportError:
    mostrar("FALTA", "pacote mcp não instalado neste Python", "pip install -r requirements.txt (rode este script com o Python da .venv)")
chave = os.environ.get("WORKER_KEY", "")
mostrar("OK" if len(chave) >= 24 else "FALTA", "WORKER_KEY definida (24+ caracteres)" if len(chave) >= 24 else "WORKER_KEY ausente ou curta no .env", "veja a etapa 5 do guia")
if not api_base:
    mostrar("AVISO", "API_BASE não definida: o worker atenderia o site PUBLICADO", "para testar local, API_BASE=http://127.0.0.1:8080 no .env")
    api_base = "https://hackathon.figueiredo.dev"
elif "127.0.0.1" not in api_base and "localhost" not in api_base:
    mostrar("AVISO", f"o worker está apontado para um site remoto: {api_base}", "confirme que é isso mesmo que você quer testar")
codigo, _ = http(f"{api_base}/api/saude")
mostrar("OK" if codigo == 200 else "FALTA", f"site responde em {api_base}" if codigo == 200 else f"site não responde em {api_base}",
        "suba o Docker, o banco e o PHP (guia, etapa 8): php -S 127.0.0.1:8080 -t site/public_html site/dev/router.php")
if codigo == 200 and chave:
    codigo, corpo = http(f"{api_base}/api/worker/telefones", {"X-Worker-Key": chave})
    if codigo == 200:
        try:
            qtd = len(json.loads(corpo))
        except ValueError:
            qtd = -1
        mostrar("OK", f"o site aceita a chave do worker (telefones aprovados no site: {qtd})")
    else:
        mostrar("FALTA", f"o site recusou a chave do worker (HTTP {codigo})", "a WORKER_KEY do .env precisa ser igual à de site/hackathon-config.php")
neo = os.environ.get("NEO4J_URI", "bolt://127.0.0.1:7689")
m = re.match(r"\w+://([^:/]+):(\d+)", neo)
mostrar("OK" if m and porta_aberta(m[1], int(m[2])) else "FALTA", "Neo4j responde" if m and porta_aberta(m[1], int(m[2])) else "Neo4j não responde",
        "docker compose --env-file .env -f infra/docker-compose.yml up -d neo4j; python coleta/carregar_neo4j.py --zerar --exemplo")
workers = processos("worker.py")
mostrar("INFO", f"worker rodando agora: {len(workers)} processo(s) (no Windows, lançador + filho contam 2 de um worker só)" if workers else "worker não está rodando")
try:
    import worker as w
    aberta = w.sessao_de_canal_aberta()
    mostrar("AVISO" if aberta else "OK", "há uma sessão `claude` de canal aberta: o worker NÃO responde ao WhatsApp enquanto ela existir" if aberta
            else "nenhuma sessão `claude` de canal aberta (o worker responde)", "feche a sessão iniciada com --dangerously-load-development-channels")
    marca = ESTADO / "worker.cursor"
    mostrar("INFO", "worker.cursor existe: mensagens que chegarem com o worker desligado serão atendidas quando ele subir" if marca.exists()
            else "worker.cursor ainda não existe (só nasce na 1ª mensagem atendida): o worker ignora o que já está no inbound; ligue-o ANTES de mandar a mensagem de teste")
except Exception as e:  # noqa: BLE001
    mostrar("AVISO", f"não consegui carregar o worker para checar a sessão de canal ({type(e).__name__})")

bloco("4. Modelos (nenhuma chamada é feita aqui)")
try:
    import agente
    cadeia = provedores.cadeia(agente.MODELO)
    mostrar("OK", "cadeia de modelos (pedido -> substitutos): " + " -> ".join(cadeia))
    claude = agente.CLAUDE
    achou = shutil.which(claude) or Path(claude).exists()
    mostrar("OK" if achou else "AVISO", "`claude` encontrado" if achou else "`claude` não encontrado", "instale o Claude Code e faça login (claude), ou use só modelos de outro provedor")
    for nome, var in (("DeepSeek", "DEEPSEEK_API_KEY"), ("Gemini", "GOOGLE_API_KEY")):
        mostrar("INFO", f"{nome}: chave {'configurada' if os.environ.get(var) else 'NÃO configurada'} (nunca impressa)")
except Exception as e:  # noqa: BLE001
    mostrar("AVISO", f"não consegui ler a cadeia de modelos ({type(e).__name__})")

bloco("5. Áudio (nota de voz) — opcional")
venv_audio = RAIZ / "inferencia" / ".venv"
mostrar("OK" if venv_audio.is_dir() else "AVISO", "venv de transcrição (faster-whisper) existe" if venv_audio.is_dir() else "inferencia/.venv não existe",
        "sem ela toda nota de voz recebe 'Não consegui entender o áudio'; o teste de texto não depende disso")
mostrar("OK" if shutil.which("ffmpeg") else "AVISO", "ffmpeg encontrado" if shutil.which("ffmpeg") else "ffmpeg não encontrado", "winget install Gyan.FFmpeg (Windows) ou apt install ffmpeg")
modelos = RAIZ / "inferencia" / "modelos" / "whisper"
mostrar("OK" if modelos.is_dir() and any(modelos.iterdir()) else "AVISO", "modelo Whisper baixado" if modelos.is_dir() and any(modelos.iterdir()) else "modelo Whisper ainda não baixado",
        "o primeiro uso baixa o modelo (precisa de internet)")

bloco("6. Segredos")
env_texto = (RAIZ / ".env").read_text(encoding="utf-8", errors="replace") if (RAIZ / ".env").exists() else ""
mostrar("AVISO" if re.search(r"^\s*WA_PAIR_PHONE\s*=\s*\S", env_texto, re.M) else "OK",
        "WA_PAIR_PHONE está gravado no .env (o número do bot ficou em arquivo)" if re.search(r"^\s*WA_PAIR_PHONE\s*=\s*\S", env_texto, re.M) else "o número do bot não está gravado no .env",
        "prefira digitar o número na hora (canal-whatsapp/parear.ps1 ou parear.sh) e apagar a linha")
cod, _ = rodar(["git", "-C", str(RAIZ), "check-ignore", "-q", ".env"])
mostrar("OK" if cod == 0 else "FALTA", ".env está no .gitignore" if cod == 0 else ".env NÃO está no .gitignore", "adicione .env ao .gitignore antes de qualquer commit")

# ------------------------------------------------------------------------------------------------------------------------
falta_parear = [r for r in resultados if r[1] == "FALTA" and r[0].startswith(("1.", "2."))]
falta_teste = [r for r in resultados if r[1] == "FALTA" and r[0].startswith(("3.", "4.", "6."))]
avisos = [r for r in resultados if r[1] == "AVISO"]
print("\n== RESUMO")
print(f"Pronto para PAREAR o número:        {'SIM' if not falta_parear else 'NÃO (' + str(len(falta_parear)) + ' pendência(s) nos blocos 1-2)'}")
print(f"Pronto para o TESTE ponta a ponta:  {'SIM' if not falta_teste and not falta_parear else 'NÃO (' + str(len(falta_teste)) + ' pendência(s) nos blocos 3-4 e 6)'}")
print(f"Avisos: {len(avisos)}")
sys.exit(1 if falta_parear else 0)
