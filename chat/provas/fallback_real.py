"""Prova do fallback com clientes de verdade (não faz parte de `unittest discover`: gasta um pouco de token).

    python chat/provas/fallback_real.py base A B C D      # qualquer subconjunto, na ordem dada

Roda a pergunta pelo mesmo caminho do site (worker.atender_site -> agente.perguntar -> provedores -> clientes reais), com a API
do site trocada por uma lista em memória e o log gravado em logs/prova-fallback.jsonl (o logs/chat.jsonl não é tocado).
Provedor "morto" = URL base apontada para uma porta fechada; "pendurado" = servidor TCP que aceita e nunca responde.
As variáveis de teste existem só dentro deste processo (mock.patch.dict) e somem quando ele termina. O .env não é lido para escrita.

  base  linha de base: ambiente original, o modelo da frente responde (se falhar, pare)
  A     provedor da frente morto (conexão recusada): o substituto responde
  B     provedor da frente pendurado: a tentativa é cortada pelo teto e o substituto responde dentro do orçamento
  C     o provedor da frente emite texto e depois falha: NÃO pode trocar
  D     todos os provedores da cadeia mortos (DeepSeek e Claude): erro tratado, sem laço
  D2    o mesmo, só com modelos do DeepSeek (falha rápida)
"""
import contextlib
import io
import json
import os
import socket
import sys
import threading
import time
from pathlib import Path
from unittest import mock

CHAT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CHAT))
import agente  # noqa: E402
import provedores  # noqa: E402
import worker  # noqa: E402  (lê o .env ao importar; só leitura)

RAIZ = agente.RAIZ
LOG_PROVA = RAIZ / "logs" / "prova-fallback.jsonl"
PERGUNTA = "quanto é 2 + 2"
TENANTS = ["pe-estado", "pe-garanhuns"]
FRENTE = "deepseek:deepseek-flash"      # primeiro da cadeia; o substituto padrão é claude-sonnet-5-5
MORTA = "http://127.0.0.1:9"            # porta fechada: a conexão é recusada na hora


@contextlib.contextmanager
def servidor_pendurado():
    """Aceita conexões TCP e nunca responde nada."""
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    s.listen(8)
    s.settimeout(0.5)
    presas, parar = [], threading.Event()

    def aceitar():
        while not parar.is_set():
            try:
                presas.append(s.accept()[0])
            except OSError:
                pass

    t = threading.Thread(target=aceitar, daemon=True)
    t.start()
    try:
        yield f"http://127.0.0.1:{s.getsockname()[1]}", presas
    finally:
        parar.set()
        t.join(2)
        for c in presas:
            c.close()
        s.close()


class Gravacao:
    """Anota o que o agente emitiu (com o tempo de cada evento) e guarda o Leitor da pergunta."""

    def __init__(self):
        self.eventos, self.leitor, self.t0 = [], None, 0.0
        self.original = agente.perguntar

    def __call__(self, texto, tenants, historico=None, leitor=None, **kw):
        self.leitor, self.t0 = leitor, time.monotonic()
        for tipo, dados in self.original(texto, tenants, historico, leitor, **kw):
            self.eventos.append((round(time.monotonic() - self.t0, 1), tipo, dados))
            yield tipo, dados


def executar(nome: str, ambiente: dict, modelo: str = FRENTE, escolher_falso=None) -> dict:
    """Uma pergunta pelo worker de verdade. Devolve as medidas."""
    saida, enviados, grav = io.StringIO(), [], Gravacao()
    pergunta = {"id": hash(nome) % 10_000, "usuario_id": f"prova-{nome}", "texto": PERGUNTA, "tenants": TENANTS}
    chamados = []
    real = provedores.escolher

    def escolher(m):
        chamados.append(m)
        return escolher_falso(m) if escolher_falso and escolher_falso(m) else real(m)

    LOG_PROVA.parent.mkdir(exist_ok=True)
    api = lambda met, rota, corpo=None: (enviados.extend((corpo or {}).get("eventos", [])), (200, None))[1]  # noqa: E731
    with mock.patch.dict(os.environ, ambiente), mock.patch.object(agente, "MODELO", modelo), \
            mock.patch.object(agente, "perguntar", grav), mock.patch.object(provedores, "escolher", escolher), \
            mock.patch.object(worker, "api", api), mock.patch.object(worker, "LOG", LOG_PROVA), \
            contextlib.redirect_stdout(saida):
        chave = os.environ.get("DEEPSEEK_API_KEY", "")
        inicio = time.monotonic()
        worker.atender_site(pergunta)
        total = round(time.monotonic() - inicio, 1)
    log = json.loads(LOG_PROVA.read_text(encoding="utf-8").splitlines()[-1])
    texto = "".join(e["dados"].get("delta", "") for e in enviados if e["tipo"] == "texto")
    vazou = bool(chave) and any(chave in x for x in (saida.getvalue(), json.dumps(log), json.dumps(enviados, default=str),
                                                      json.dumps([e[1:] for e in grav.eventos], default=str)))
    leitor = grav.leitor
    return {"cenario": nome, "total_s": total, "modelos_consultados_em_escolher": chamados,
            "eventos_do_agente": [(t, tp, d if tp != "texto" else {"delta": d["delta"][:80]}) for t, tp, d in grav.eventos],
            "enviado_ao_site": [(e["tipo"], e["dados"] if e["tipo"] != "texto" else e["dados"]["delta"][:120]) for e in enviados],
            "resposta": texto, "uso_de_quem_respondeu": leitor.uso if leitor else None, "log": log,
            "terminal": [l for l in saida.getvalue().splitlines() if l.strip()], "chave_apareceu_em_algum_lugar": vazou}


def cenario_base():
    return executar("base", {})


def cenario_a():
    return executar("A", {"DEEPSEEK_BASE_URL": MORTA})


def cenario_b():
    with servidor_pendurado() as (url, presas):
        r = executar("B", {"DEEPSEEK_BASE_URL": url})
        r["conexoes_aceitas_pelo_servidor_falso"] = len(presas)
    return r


def cenario_c():
    class FalaEFalha:
        def perguntar(self, texto, tenants, historico, leitor, limite_s=None):
            for pedaco in ("O resultado ", "é qua"):
                leitor.resposta += pedaco
                yield ("texto", {"delta": pedaco})
            yield ("erro", {"motivo": "conexão caiu no meio da resposta (simulado)"})

    return executar("C", {}, escolher_falso=lambda m: FalaEFalha() if m == FRENTE else None)


def cenario_d():
    # DeepSeek e Claude (o `claude` respeita ANTHROPIC_BASE_URL) apontados para a porta fechada
    return executar("D", {"DEEPSEEK_BASE_URL": MORTA, "ANTHROPIC_BASE_URL": MORTA})


def cenario_d2():
    # variante rápida de D: a cadeia só tem modelos do DeepSeek, todos com a URL morta (ninguém demora a falhar)
    return executar("D2", {"DEEPSEEK_BASE_URL": MORTA, "AGENTE_FALLBACK_ORDEM": "deepseek:deepseek-v4-pro"})


CENARIOS = {"base": cenario_base, "A": cenario_a, "B": cenario_b, "C": cenario_c, "D": cenario_d, "D2": cenario_d2}

if __name__ == "__main__":
    for nome in sys.argv[1:] or ["base"]:
        print(f"\n===== {nome} =====", flush=True)
        print(json.dumps(CENARIOS[nome](), ensure_ascii=False, indent=1, default=str), flush=True)
