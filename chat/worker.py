"""Worker do notebook: atende o site e o WhatsApp com o agente isolado.

    python chat/worker.py                          # com a .venv ativada (Linux e Windows)
    python chat/worker.py --simular "Quais contratos temos?" [numero]   # não envia WhatsApp

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
_ENV = RAIZ / ".env"
for linha in (_ENV.read_text(encoding="utf-8-sig").splitlines() if _ENV.exists() else []):   # sem .env, vale o ambiente do sistema
    if "=" in linha and not linha.lstrip().startswith("#"):
        k, v = linha.split("=", 1)
        if v.strip():      # valor vazio (ex.: chave de API não preenchida) não vira variável
            os.environ.setdefault(k.strip(), v.strip())

API = os.environ.get("API_BASE", f"https://{os.environ.get('SITE', 'hackathon.figueiredo.dev')}") + "/api"
CHAVE = os.environ["WORKER_KEY"]
ESTADO = Path(os.environ.get("WHATSAPP_STATE_DIR", Path.home() / ".claude/channels/whatsapp-hackathon"))
LOG = RAIZ / "logs" / "chat.jsonl"
_VENV_AUDIO = RAIZ / "inferencia" / ".venv"      # inferencia/ fica na raiz do projeto, ao lado de chat/
PYTHON_AUDIO = _VENV_AUDIO / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
TRANSCRITOR = RAIZ / "inferencia" / "transcrever.py"
PERFIL_MANUAL = ["pe-estado", "pe-garanhuns"]   # números liberados pelo dono no terminal
ERRO_PADRAO = "Não consegui concluir agora. Tente de novo em instantes."
AGENTES_SITE = int(os.environ.get("AGENTES_SITE", "3"))   # o WhatsApp tem o próprio agente, um por vez

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


def mensagem_de_falha(dados: dict) -> tuple:
    """Linha de terminal para um erro do agente. Quando todos os modelos da cadeia falharam, diz quais foram tentados."""
    if dados.get("nenhum_respondeu"):
        return ("agente falhou: nenhum provedor respondeu (tentados:", ", ".join(dados.get("tentados", [])) + ") |", dados.get("motivo", "")[:160])
    return ("agente falhou:", dados.get("motivo", "")[:200])


def campos_do_modelo(leitor) -> dict:
    """Para o log provar, numa demonstração, quem foi pedido, quem respondeu e se houve troca. Só nomes de modelo e frases
    curtas de motivo: nenhuma chave passa por aqui."""
    return {"modelo_pedido": leitor.modelo_pedido, "modelo": leitor.modelo, "tentados": list(leitor.tentados),
            "trocas": [{k: t[k] for k in ("de", "para", "motivo", "tentativa")} for t in leitor.trocas]}


def api(metodo: str, rota: str, corpo=None):
    req = urllib.request.Request(
        API + rota, method=metodo, data=json.dumps(corpo).encode() if corpo is not None else None,
        headers={"X-Worker-Key": CHAVE, "Content-Type": "application/json", "User-Agent": "fornexia-worker/1"},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            texto = r.read().decode("utf-8", errors="replace")
            try:
                return r.status, json.loads(texto) if texto else None
            except ValueError:      # página de erro da hospedagem com status 200: conta como falha do servidor, nunca derruba o laço
                return 502, None
    except urllib.error.HTTPError as e:
        return e.code, None


class Lote:
    """Junta os eventos e envia a cada 300 ms. Repetir um seq é seguro na API.
    Evento que não chegou (rede ou 5xx) fica na fila e segue no próximo envio, nunca é descartado: o `fim` pode estar nele."""

    POR_LOTE = 100          # o mesmo teto da API (EVENTOS_POR_LOTE)

    def __init__(self, pergunta_id: int):
        self.id, self.seq, self.fila, self.ultimo, self.encerrada = pergunta_id, 0, [], 0.0, False
        self.travados: set[int] = set()     # seq que já saiu (ou tentou sair): o servidor ignora um seq repetido, então não se acrescenta texto a ele

    def adicionar(self, tipo: str, dados: dict):
        ultimo = self.fila[-1] if self.fila else None
        if tipo == "texto" and ultimo and ultimo["tipo"] == "texto" and ultimo["seq"] not in self.travados:
            ultimo["dados"]["delta"] += dados["delta"]
        else:
            self.seq += 1
            self.fila.append({"seq": self.seq, "tipo": tipo, "dados": dados})
        if tipo != "texto" or time.monotonic() - self.ultimo >= 0.3:
            self.enviar()

    def _postar(self, parte: list) -> bool:
        """True quando a API respondeu e não adianta repetir (sucesso ou recusa); False quando vale tentar de novo depois."""
        self.travados.update(e["seq"] for e in parte)
        for tentativa in range(3):
            try:
                status, _ = api("POST", f"/worker/perguntas/{self.id}/eventos", {"eventos": parte})
            except OSError:
                time.sleep(1 + tentativa)
                continue
            if status == 409:      # o site encerrou a pergunta por tempo
                self.encerrada = True
            if status < 500:       # erro do servidor é passageiro: repetir um seq é seguro
                return True
            registrar("eventos: API respondeu", status)
            time.sleep(1 + tentativa)
        return False

    def enviar(self):
        while self.fila and not self.encerrada:
            parte = self.fila[:self.POR_LOTE]
            if not self._postar(parte):
                break
            self.fila = self.fila[len(parte):]
        self.ultimo = time.monotonic()


def atender_site(p: dict):
    inicio = time.monotonic()
    lote, leitor, primeiro = Lote(p["id"]), agente.Leitor(), None
    chave = f"site:{p['usuario_id']}"
    desfecho = "erro"
    try:
        for tipo, dados in agente.perguntar(p["texto"], p["tenants"], list(historicos[chave]), leitor):
            if tipo == "fallback":
                # Só vai para o terminal e para o log. A API do site só aceita consulta/texto/fonte/fim/erro (um tipo novo
                # derrubaria o lote inteiro com 400), e a resposta ao usuário não muda de tom por causa da troca.
                registrar("fallback:", dados.get("de"), "->", dados.get("para"), "|", dados.get("motivo", "")[:120])
                continue
            primeiro = primeiro or int((time.monotonic() - inicio) * 1000)
            if tipo == "erro":
                registrar(*mensagem_de_falha(dados))
                dados = {"motivo": dados["motivo"] if "demorou" in dados.get("motivo", "") else ERRO_PADRAO}
            elif tipo == "fim":
                desfecho = "concluida"
            if tipo in ("fim", "erro"):
                dados = {**dados, **campos_do_modelo(leitor)}    # o site guarda quem respondeu, para o pacote de prova
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
               **campos_do_modelo(leitor),
               primeiro_sinal_ms=primeiro, duracao_ms=int((time.monotonic() - inicio) * 1000))


def laco_site(atraso: float = 0):
    parar.wait(atraso)      # espalha as buscas: os agentes não consultam a fila no mesmo instante
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
        except Exception as e:      # um erro inesperado não pode matar a thread deste agente em silêncio
            registrar("site: falha inesperada:", type(e).__name__, str(e)[:200])
            espera = min(espera * 2, 30)
        parar.wait(espera)


# ---------- WhatsApp ----------
def normalizar(numero: str) -> str:
    d = re.sub(r"\D", "", numero)
    return d[:4] + d[5:] if re.fullmatch(r"55\d{2}9\d{8}", d) else d


def tenants_do_numero(numero: str) -> list[str]:
    """Entes de quem escreve. Número do site: os do plano dele. Número que o dono liberou no terminal (não está no site): PERFIL_MANUAL.
    Lê `perfis_por_numero` uma vez só, porque a sincronização troca o dicionário inteiro por outro."""
    return perfis_por_numero.get(normalizar(numero), PERFIL_MANUAL)


def escrever_atomico(caminho: Path, conteudo: str):
    tmp = caminho.with_suffix(caminho.suffix + ".tmp")
    tmp.write_text(conteudo, encoding="utf-8")
    tmp.replace(caminho)


def pedir(pedido: dict):
    pedido["id"] = f"{int(time.time() * 1000)}-{''.join(random.choices(string.ascii_lowercase + string.digits, k=6))}"
    outbox = ESTADO / "outbox"
    tmp = outbox / f".{pedido['id']}.tmp"
    tmp.write_text(json.dumps(pedido, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, outbox / f"{pedido['id']}.json")   # atômico e funciona também no Windows


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
                registrar(*mensagem_de_falha(dados))
            elif tipo == "fallback":
                registrar("fallback:", dados.get("de"), "->", dados.get("para"), "|", dados.get("motivo", "")[:120])
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
    tenants = tenants_do_numero(m.get("remetente", ""))
    inicio = time.monotonic()
    saida, leitor, desfecho = responder_whatsapp(texto, tenants, f"wa:{chat}")
    pedir({"op": "enviar", "chat_id": chat, "texto": saida})
    gravar_log(canal="whatsapp", id=m["id"], tenants=tenants, pergunta=texto, consultas=leitor.consultas,
               evidencias=leitor.evidencias, desfecho=desfecho, **campos_do_modelo(leitor),
               duracao_ms=int((time.monotonic() - inicio) * 1000))


MARCA_DA_SESSAO = "dangerously-load-development-channels"


def sessao_de_canal_aberta() -> bool:
    """Há uma sessão `claude` ouvindo o WhatsApp? Se sim, o worker não responde (as duas responderiam).
    Linux/macOS: pgrep. Windows: PowerShell (o comando de si mesmo é excluído por $PID). Se não der para saber, diz que não."""
    try:
        if os.name == "nt":
            filtro = f"$_.CommandLine -like '*{MARCA_DA_SESSAO}*' -and $_.ProcessId -ne $PID"
            r = subprocess.run(["powershell", "-NoProfile", "-Command", f"@(Get-CimInstance Win32_Process | Where-Object {{ {filtro} }}).Count"],
                               capture_output=True, text=True, timeout=15)
            return r.returncode == 0 and r.stdout.strip() not in ("", "0")
        return subprocess.run(["pgrep", "-f", MARCA_DA_SESSAO], capture_output=True, timeout=10).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def laco_whatsapp():
    arquivo, marca = ESTADO / "inbound.jsonl", ESTADO / "worker.cursor"
    tamanho = lambda: arquivo.stat().st_size if arquivo.exists() else 0  # noqa: E731
    cursor = int(marca.read_text()) if marca.exists() else tamanho()   # na primeira vez, ignora o histórico
    while not parar.is_set():
        try:
            cursor = _passo_whatsapp(arquivo, marca, tamanho, cursor)
        except Exception as e:      # idem: a thread do WhatsApp não morre por um erro de leitura
            registrar("whatsapp: falha inesperada:", type(e).__name__, str(e)[:200])
        parar.wait(1)


def _passo_whatsapp(arquivo: Path, marca: Path, tamanho, cursor: int) -> int:
    """Uma volta do laço: atende o que chegou desde o cursor e devolve o cursor novo."""
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
    return cursor


def sincronizar_telefones():
    """Aprovado no site entra na lista do gateway; revogado sai. Quem o dono liberou à mão nunca é tocado."""
    status, lista = api("GET", "/worker/telefones")
    if status != 200 or lista is None:
        return
    novos = {normalizar(t["numero"]): t["tenants"] for t in lista}
    global perfis_por_numero
    perfis_por_numero = novos       # troca a referência de uma vez: clear()+update() deixava uma janela em que todo número caía no perfil amplo

    caminho, marca = ESTADO / "access.json", ESTADO / "sincronizados.json"
    if not caminho.exists():    # gateway do WhatsApp nunca rodou aqui: só o site funciona, e isso não é erro
        return
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
        tenants = tenants_do_numero(numero)
        print(responder_whatsapp(sys.argv[i + 1], tenants, "simulado")[0])
        return 0
    signal.signal(signal.SIGTERM, lambda *_: parar.set())
    signal.signal(signal.SIGINT, lambda *_: parar.set())
    laços = [threading.Thread(target=laco_site, args=(i * 0.5,), daemon=True) for i in range(AGENTES_SITE)]
    laços += [threading.Thread(target=f, daemon=True) for f in (laco_whatsapp, laco_telefones)]
    for t in laços:
        t.start()
    registrar("worker no ar:", API, f"com {AGENTES_SITE} agentes no site")
    parar.wait()
    return 0


if __name__ == "__main__":
    sys.exit(main())
