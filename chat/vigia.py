"""Vigia de saúde: escreve em logs/saude.jsonl quando cada peça cai e quando volta, com a duração da queda.

    python chat/vigia.py            # com a .venv ativada; o ligar-tudo já sobe este processo

Por que um processo separado: se o worker ou o gateway morrem, eles mesmos não conseguem avisar. O vigia é quem está vivo para escrever.

O que ele observa (a cada VIGIA_INTERVALO_S, padrão 15 s):
  worker   batimento em logs/saude-worker.json (o worker o renova a cada 10 s; parado há mais de 45 s = fora)
  gateway  campo `atualizado` do status.json (o gateway o renova a cada 30 s; mais de 90 s sem mudar = fora) e `conectado`
  site     GET {API_BASE}/api/me (qualquer resposta abaixo de 500 conta como no ar)
  neo4j    conexão TCP com o NEO4J_URI

Eventos (subsistema "saude"; o nível sobe com a gravidade):
  componente_caiu                 aviso  componente, desde (último sinal de vida conhecido), detectado_em, motivo
  componente_fora_alem_do_limite  erro   componente, desde, fora_ha_s, limite_s   (uma vez por queda; contado desde o último sinal de vida; padrão 120 s = 2 minutos)
  componente_voltou               info   componente, inicio_queda, fim_queda, duracao_s, passou_do_limite
  vigia_iniciou / vigia_parou     info   (e vigia_ficou_cego, aviso, se ele mesmo ficou parado: não viu o que aconteceu nesse intervalo)

O estado fica em logs/saude-estado.json: se o vigia reiniciar no meio de uma queda, a queda continua contando do início certo.
Limite conhecido: se o próprio vigia estiver parado, ninguém escreve. Por isso ele também registra o intervalo em que ficou cego.
"""

import json
import os
import signal
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "consulta"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import provedores  # noqa: E402,F401  (só para carregar o .env, como o worker)
import registro  # noqa: E402

COMPONENTES_PADRAO = "gateway,worker,site,neo4j"
LIMITE_BATIMENTO_WORKER_S = 45
LIMITE_BATIMENTO_GATEWAY_S = 90


def _iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch).astimezone().isoformat(timespec="milliseconds")


def _ler_json(caminho: Path) -> dict | None:
    try:
        dado = json.loads(caminho.read_text(encoding="utf-8"))
        return dado if isinstance(dado, dict) else None
    except (OSError, ValueError):
        return None


# ---------- as checagens: cada uma devolve (está bem?, motivo curto) ou, quando falha e sabe desde quando, (False, motivo, desde_epoch) ----------
# O `desde` é o último sinal de vida conhecido (batimento, status.json): a queda conta do início real, não de quando o vigia notou.
def checar_worker(agora, pasta: Path | None = None):
    d = _ler_json((pasta or registro.pasta()) / "saude-worker.json")
    if not d:
        return False, "sem batimento (worker não iniciou ou o arquivo sumiu)"
    ultimo = float(d.get("ts_epoch") or 0)
    if d.get("parando"):
        return False, "parado de forma limpa", ultimo
    idade = agora() - ultimo
    if idade > LIMITE_BATIMENTO_WORKER_S:
        return False, f"sem batimento há {int(idade)} s", ultimo
    return True, ""


def checar_gateway(agora, estado: Path | None = None):
    estado = estado or Path(os.environ.get("WHATSAPP_STATE_DIR") or Path.home() / ".claude/channels/whatsapp-hackathon")
    d = _ler_json(estado / "status.json")
    if not d:
        return False, "status.json ausente (gateway nunca rodou ou o arquivo sumiu)"
    try:
        ultimo = datetime.fromisoformat(str(d["atualizado"]).replace("Z", "+00:00")).timestamp()
    except (KeyError, ValueError):
        return False, "status.json sem horário de atualização"
    if d.get("parado"):
        return False, "parado de forma limpa", ultimo
    idade = agora() - ultimo
    if idade > LIMITE_BATIMENTO_GATEWAY_S:
        return False, f"sem sinal há {int(idade)} s", ultimo
    if d.get("conectado") is not True:
        return False, "gateway no ar, mas sem conexão com o WhatsApp", ultimo
    return True, ""


def checar_site(api_base: str, timeout: float = 5):
    try:
        with urllib.request.urlopen(api_base.rstrip("/") + "/api/me", timeout=timeout):
            return True, ""
    except urllib.error.HTTPError as e:
        e.close()
        return (e.code < 500), ("" if e.code < 500 else f"HTTP {e.code}")
    except (urllib.error.URLError, OSError) as e:
        return False, f"sem resposta ({type(getattr(e, 'reason', e)).__name__})"


def checar_neo4j(uri: str, timeout: float = 3):
    p = urlparse(uri)
    try:
        with socket.create_connection((p.hostname or "127.0.0.1", p.port or 7687), timeout=timeout):
            return True, ""
    except OSError as e:
        return False, f"sem conexão ({type(e).__name__})"


class Vigia:
    """Máquina de estados por componente. `checagens` e `relogio` são injetáveis para testar sem esperar minutos."""

    def __init__(self, checagens: dict, limite_s: float = 120, intervalo_s: float = 15, relogio=time.time, arquivo_estado: Path | None = None):
        self.checagens, self.limite_s, self.intervalo_s, self.relogio = checagens, limite_s, intervalo_s, relogio
        self.arquivo = arquivo_estado or registro.pasta() / "saude-estado.json"
        salvo = _ler_json(self.arquivo) or {}
        self.estado: dict = salvo.get("componentes", {})
        self.ultimo_passo: float | None = salvo.get("ultimo_passo")

    def iniciar(self):
        agora = self.relogio()
        cego = agora - self.ultimo_passo if self.ultimo_passo else None
        registro.registrar("saude", "vigia_iniciou", "info", pid=os.getpid(), componentes=sorted(self.checagens),
                           limite_s=self.limite_s, intervalo_s=self.intervalo_s)
        if cego is not None and cego > self.intervalo_s * 2 + 5:
            registro.registrar("saude", "vigia_ficou_cego", "aviso", de=_iso(self.ultimo_passo), ate=_iso(agora), duracao_s=round(cego, 1),
                               observacao="o vigia estava parado: o que aconteceu nesse intervalo não foi observado")

    def passo(self):
        agora = self.relogio()
        for nome, checar in self.checagens.items():
            desde = agora
            try:
                resultado = checar()
                bem, motivo = resultado[0], resultado[1]
                if len(resultado) > 2 and resultado[2]:
                    desde = min(float(resultado[2]), agora)       # início real conhecido (último sinal de vida)
            except Exception as e:  # noqa: BLE001  uma checagem com defeito não pode derrubar as outras
                bem, motivo = False, f"a checagem falhou ({type(e).__name__})"
            atual = self.estado.get(nome)
            if bem:
                if atual and atual.get("estado") == "fora":
                    duracao = agora - atual["desde"]
                    registro.registrar("saude", "componente_voltou", "info", componente=nome, inicio_queda=_iso(atual["desde"]),
                                       fim_queda=_iso(agora), duracao_s=round(duracao, 1), passou_do_limite=duracao >= self.limite_s,
                                       motivo_da_queda=atual.get("motivo"))
                self.estado[nome] = {"estado": "ok", "desde": agora}
                continue
            if not atual or atual.get("estado") != "fora":
                self.estado[nome] = atual = {"estado": "fora", "desde": desde, "alertou": False, "motivo": motivo}
                registro.registrar("saude", "componente_caiu", "aviso", componente=nome, desde=_iso(desde), detectado_em=_iso(agora), motivo=motivo)
            atual["motivo"] = motivo
            if not atual.get("alertou") and agora - atual["desde"] >= self.limite_s:
                atual["alertou"] = True
                registro.registrar("saude", "componente_fora_alem_do_limite", "erro", componente=nome, desde=_iso(atual["desde"]),
                                   fora_ha_s=round(agora - atual["desde"], 1), limite_s=self.limite_s, motivo=motivo)
        self.ultimo_passo = agora
        self._salvar()

    def _salvar(self):
        try:
            self.arquivo.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.arquivo.with_suffix(".tmp")
            tmp.write_text(json.dumps({"componentes": self.estado, "ultimo_passo": self.ultimo_passo}), encoding="utf-8")
            os.replace(tmp, self.arquivo)
        except OSError:
            pass


def montar_checagens(componentes: list[str]) -> dict:
    todas = {
        "worker": lambda: checar_worker(time.time),
        "gateway": lambda: checar_gateway(time.time),
        "site": lambda: checar_site(os.environ.get("API_BASE", "http://127.0.0.1:8080")),
        "neo4j": lambda: checar_neo4j(os.environ.get("NEO4J_URI", "bolt://127.0.0.1:7689")),
    }
    desconhecidos = [c for c in componentes if c not in todas]
    if desconhecidos:
        raise SystemExit(f"VIGIA_COMPONENTES com nome desconhecido: {', '.join(desconhecidos)} (válidos: {', '.join(todas)})")
    return {c: todas[c] for c in componentes}


def main() -> int:
    componentes = [c.strip() for c in os.environ.get("VIGIA_COMPONENTES", COMPONENTES_PADRAO).split(",") if c.strip()]
    intervalo = float(os.environ.get("VIGIA_INTERVALO_S", "15"))
    vigia = Vigia(montar_checagens(componentes), limite_s=float(os.environ.get("VIGIA_LIMITE_S", "120")), intervalo_s=intervalo)
    parar = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: parar.set())
    signal.signal(signal.SIGINT, lambda *_: parar.set())
    vigia.iniciar()
    print(time.strftime("%H:%M:%S"), "vigia no ar:", ", ".join(componentes), f"(a cada {intervalo:g} s; alerta após {vigia.limite_s:g} s fora)", flush=True)
    while not parar.is_set():
        vigia.passo()
        parar.wait(intervalo)
    registro.registrar("saude", "vigia_parou", "info", pid=os.getpid())
    return 0


if __name__ == "__main__":
    sys.exit(main())
