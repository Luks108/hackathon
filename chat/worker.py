"""Worker do notebook: atende o site e o WhatsApp com o agente isolado.

    .venv/bin/python chat/worker.py
    .venv/bin/python chat/worker.py --simular "Quais contratos temos?" [numero]   # não envia WhatsApp

O notebook só faz conexões de saída: busca perguntas na API do site e lê a fila do gateway.
Não pode rodar junto da sessão `claude --dangerously-load-development-channels`: os dois responderiam.
"""

import collections
import json
import os
import random
import re
import signal
import string
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import agente  # noqa: E402

RAIZ = agente.RAIZ
for linha in (RAIZ / ".env").read_text(encoding="utf-8").splitlines():
    if "=" in linha and not linha.lstrip().startswith("#"):
        k, v = linha.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

API = os.environ.get("API_BASE", f"https://{os.environ.get('SITE', 'hackathon.figueiredo.dev')}") + "/api"
CHAVE = os.environ["WORKER_KEY"]
ESTADO = Path(os.environ.get("WHATSAPP_STATE_DIR", Path.home() / ".claude/channels/whatsapp-hackathon"))
LOG = RAIZ / "logs" / "chat.jsonl"
PYTHON_AUDIO = RAIZ.parent / "inferencia" / ".venv" / "bin" / "python"
TRANSCRITOR = RAIZ.parent / "inferencia" / "transcrever.py"
PERFIL_MANUAL = ["pe-estado", "pe-garanhuns"]   # números liberados pelo dono no terminal
ERRO_PADRAO = "Não consegui concluir agora. Tente de novo em instantes."

parar = threading.Event()
historicos: dict[str, collections.deque] = collections.defaultdict(lambda: collections.deque(maxlen=3))
perfis_por_numero: dict[str, list[str]] = {}


def registrar(*partes):
    print(time.strftime("%H:%M:%S"), *partes, flush=True)


def gravar_log(**campos):
    LOG.parent.mkdir(exist_ok=True)
    campos["pergunta"] = agente.CPF.sub("[CPF]", campos.get("pergunta", ""))
    with LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"em": time.strftime("%Y-%m-%dT%H:%M:%S%z"), **campos}, ensure_ascii=False) + "\n")


def api(metodo: str, rota: str, corpo=None):
    req = urllib.request.Request(
        API + rota, method=metodo, data=json.dumps(corpo).encode() if corpo is not None else None,
        headers={"X-Worker-Key": CHAVE, "Content-Type": "application/json", "User-Agent": "fornexia-worker/1"},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            texto = r.read().decode("utf-8")
            return r.status, json.loads(texto) if texto else None
    except urllib.error.HTTPError as e:
        return e.code, None


class Lote:
    """Junta os eventos e envia a cada 300 ms. Repetir um seq é seguro na API."""

    def __init__(self, pergunta_id: int):
        self.id, self.seq, self.fila, self.ultimo, self.encerrada = pergunta_id, 0, [], 0.0, False

    def adicionar(self, tipo: str, dados: dict):
        ultimo = self.fila[-1] if self.fila else None
        if tipo == "texto" and ultimo and ultimo["tipo"] == "texto":
            ultimo["dados"]["delta"] += dados["delta"]
        else:
            self.seq += 1
            self.fila.append({"seq": self.seq, "tipo": tipo, "dados": dados})
        if tipo != "texto" or time.monotonic() - self.ultimo >= 0.3:
            self.enviar()

    def enviar(self):
        if not self.fila or self.encerrada:
            return
        for tentativa in range(3):
            try:
                status, _ = api("POST", f"/worker/perguntas/{self.id}/eventos", {"eventos": self.fila})
            except OSError:
                time.sleep(1 + tentativa)
                continue
            if status == 409:      # o site encerrou a pergunta por tempo
                self.encerrada = True
            break
        self.fila, self.ultimo = [], time.monotonic()


def atender_site(p: dict):
    inicio = time.monotonic()
    lote, leitor, primeiro = Lote(p["id"]), agente.Leitor(), None
    chave = f"site:{p['usuario_id']}"
    desfecho = "erro"
    try:
        for tipo, dados in agente.perguntar(p["texto"], p["tenants"], list(historicos[chave]), leitor):
            primeiro = primeiro or int((time.monotonic() - inicio) * 1000)
            if tipo == "erro":
                registrar("agente falhou:", dados.get("motivo", "")[:200])
                dados = {"motivo": dados["motivo"] if "demorou" in dados.get("motivo", "") else ERRO_PADRAO}
            elif tipo == "fim":
                desfecho = "concluida"
            lote.adicionar(tipo, dados)
            if lote.encerrada:
                return
    except Exception as e:  # a tela precisa de uma resposta, nunca de silêncio
        registrar("falha no site:", type(e).__name__, str(e)[:200])
        lote.adicionar("erro", {"motivo": ERRO_PADRAO})
    lote.enviar()
    if desfecho == "concluida" and leitor.resposta:
        historicos[chave].append((p["texto"], leitor.resposta[:600]))
    gravar_log(canal="site", id=p["id"], usuario=p["usuario_id"], tenants=p["tenants"], pergunta=p["texto"],
               consultas=leitor.consultas, evidencias=leitor.evidencias, desfecho=desfecho,
               primeiro_sinal_ms=primeiro, duracao_ms=int((time.monotonic() - inicio) * 1000))


def laco_site():
    espera = 1.5
    while not parar.is_set():
        try:
            status, p = api("POST", "/worker/proxima")
            espera = 1.5
            if status == 200 and p:
                registrar("site: pergunta", p["id"], p["tenants"])
                atender_site(p)
                continue
            if status not in (200, 204):
                registrar("site: API respondeu", status)
        except OSError as e:
            registrar("site: rede", str(e)[:120])
            espera = min(espera * 2, 30)
        parar.wait(espera)


# ---------- WhatsApp ----------
def normalizar(numero: str) -> str:
    d = re.sub(r"\D", "", numero)
    return d[:4] + d[5:] if re.fullmatch(r"55\d{2}9\d{8}", d) else d


def escrever_atomico(caminho: Path, conteudo: str):
    tmp = caminho.with_suffix(caminho.suffix + ".tmp")
    tmp.write_text(conteudo, encoding="utf-8")
    tmp.replace(caminho)


def pedir(pedido: dict):
    pedido["id"] = f"{int(time.time() * 1000)}-{''.join(random.choices(string.ascii_lowercase + string.digits, k=6))}"
    outbox = ESTADO / "outbox"
    tmp = outbox / f".{pedido['id']}.tmp"
    tmp.write_text(json.dumps(pedido, ensure_ascii=False), encoding="utf-8")
    tmp.rename(outbox / f"{pedido['id']}.json")


def texto_whatsapp(resposta: str, fontes: list[dict]) -> str:
    partes = [resposta.strip() or ERRO_PADRAO]
    for f in fontes[:3]:
        trecho = f["trecho"] if len(f["trecho"]) <= 180 else f["trecho"][:180].rsplit(" ", 1)[0] + "…"
        data = "/".join(reversed(str(f.get("capturado_em") or "").split("-")))
        partes.append(f"📎 \"{trecho}\"\nCaptura: {data}" + (f"\n{f['url']}" if f.get("url") else ""))
    return "\n\n".join(partes)[:3800]


def transcrever(arquivo: str) -> str | None:
    try:
        r = subprocess.run([str(PYTHON_AUDIO), str(TRANSCRITOR), arquivo], capture_output=True, text=True, timeout=90)
        return r.stdout.strip() or None if r.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def responder_whatsapp(texto: str, tenants: list[str], chave: str) -> tuple[str, agente.Leitor, str]:
    leitor, fontes, desfecho = agente.Leitor(), [], "erro"
    try:
        for tipo, dados in agente.perguntar(texto, tenants, list(historicos[chave]), leitor):
            if tipo == "fonte":
                fontes.append(dados)
            elif tipo == "fim":
                desfecho = "concluida"
            elif tipo == "erro":
                registrar("agente falhou:", dados.get("motivo", "")[:200])
    except Exception as e:
        registrar("falha no WhatsApp:", type(e).__name__, str(e)[:200])
    if desfecho != "concluida" or not leitor.resposta:
        return ERRO_PADRAO, leitor, "erro"
    historicos[chave].append((texto, leitor.resposta[:600]))
    return texto_whatsapp(leitor.resposta, fontes), leitor, desfecho


def atender_whatsapp(m: dict):
    chat = m["chat_id"]
    if m["tipo"] == "audio" and m.get("arquivo"):
        texto = transcrever(m["arquivo"])
        if not texto:
            pedir({"op": "enviar", "chat_id": chat, "texto": "Não consegui entender o áudio. Pode mandar por texto?"})
            return
    elif m["tipo"] == "texto":
        texto = m["texto"].strip()
    else:
        pedir({"op": "enviar", "chat_id": chat, "texto": "Por aqui eu respondo perguntas por texto ou áudio sobre fornecedores."})
        return
    if not texto:
        return
    texto = texto[:500]
    pedir({"op": "reagir", "chat_id": chat, "message_id": m["id"], "emoji": "👀"})
    pedir({"op": "digitando", "chat_id": chat, "ligado": True})
    tenants = perfis_por_numero.get(normalizar(m.get("remetente", "")), PERFIL_MANUAL)
    inicio = time.monotonic()
    saida, leitor, desfecho = responder_whatsapp(texto, tenants, f"wa:{chat}")
    pedir({"op": "enviar", "chat_id": chat, "texto": saida})
    gravar_log(canal="whatsapp", id=m["id"], tenants=tenants, pergunta=texto, consultas=leitor.consultas,
               evidencias=leitor.evidencias, desfecho=desfecho, duracao_ms=int((time.monotonic() - inicio) * 1000))


def sessao_de_canal_aberta() -> bool:
    return subprocess.run(["pgrep", "-f", "dangerously-load-development-channels"], capture_output=True).returncode == 0


def laco_whatsapp():
    arquivo, marca = ESTADO / "inbound.jsonl", ESTADO / "worker.cursor"
    tamanho = lambda: arquivo.stat().st_size if arquivo.exists() else 0  # noqa: E731
    cursor = int(marca.read_text()) if marca.exists() else tamanho()   # na primeira vez, ignora o histórico
    while not parar.is_set():
        if tamanho() < cursor:
            cursor = 0
        if tamanho() > cursor and not sessao_de_canal_aberta():
            with arquivo.open("rb") as f:
                f.seek(cursor)
                bloco = f.read()
            completo = bloco[:bloco.rfind(b"\n") + 1]
            cursor += len(completo)
            marca.write_text(str(cursor))
            for linha in completo.splitlines():
                try:
                    m = json.loads(linha)
                    registrar("whatsapp:", m.get("tipo"))
                    atender_whatsapp(m)
                except Exception as e:
                    registrar("falha ao atender:", type(e).__name__, str(e)[:200])
        parar.wait(1)


def sincronizar_telefones():
    """Aprovado no site entra na lista do gateway; revogado sai. Quem o dono liberou à mão nunca é tocado."""
    status, lista = api("GET", "/worker/telefones")
    if status != 200 or lista is None:
        return
    novos = {normalizar(t["numero"]): t["tenants"] for t in lista}
    perfis_por_numero.clear()
    perfis_por_numero.update(novos)

    caminho, marca = ESTADO / "access.json", ESTADO / "sincronizados.json"
    acesso = json.loads(caminho.read_text(encoding="utf-8"))
    nossos = set(json.loads(marca.read_text(encoding="utf-8"))) if marca.exists() else set()
    lista_atual = acesso.get("allowFrom", [])
    dono = normalizar(lista_atual[0]) if lista_atual else None
    atuais = {normalizar(n) for n in lista_atual}
    manter = [n for n in lista_atual if normalizar(n) == dono or normalizar(n) not in nossos or normalizar(n) in novos]
    entrar = [n for n in novos if n not in atuais]
    nossos = (nossos | set(entrar)) & set(novos)
    if entrar or len(manter) != len(lista_atual):
        acesso["allowFrom"] = manter + entrar
        escrever_atomico(caminho, json.dumps(acesso, ensure_ascii=False, indent=2))
        registrar("telefones: entraram", len(entrar), "saíram", len(lista_atual) - len(manter))
    escrever_atomico(marca, json.dumps(sorted(nossos)))


def laco_telefones():
    while not parar.is_set():
        try:
            sincronizar_telefones()
        except (OSError, ValueError) as e:
            registrar("telefones:", type(e).__name__, str(e)[:120])
        parar.wait(15)


def main() -> int:
    if "--simular" in sys.argv:
        i = sys.argv.index("--simular")
        numero = sys.argv[i + 2] if len(sys.argv) > i + 2 else ""
        tenants = perfis_por_numero.get(normalizar(numero), PERFIL_MANUAL)
        print(responder_whatsapp(sys.argv[i + 1], tenants, "simulado")[0])
        return 0
    signal.signal(signal.SIGTERM, lambda *_: parar.set())
    signal.signal(signal.SIGINT, lambda *_: parar.set())
    laços = [threading.Thread(target=f, daemon=True) for f in (laco_site, laco_whatsapp, laco_telefones)]
    for t in laços:
        t.start()
    registrar("worker no ar:", API)
    parar.wait()
    return 0


if __name__ == "__main__":
    sys.exit(main())
