"""Teste de carga do site: várias contas fazem uma pergunta ao mesmo tempo, pela API de verdade.

    python bench/carga.py                                   # 8 pessoas em http://127.0.0.1:8080
    python bench/carga.py http://127.0.0.1:8080 --pessoas 8

O worker precisa estar rodando (python chat/worker.py) e o Neo4j com os dados. Cada pessoa é uma conta de teste
(carga01@local.test ...), criada na primeira vez; o e-mail é fixo para a rodada poder repetir.
Mede, por pessoa: quando saiu da fila, quando veio o primeiro sinal e quando a resposta terminou.
No total: duração, latência média das requisições, erros 5xx e a memória extra dos processos `claude`.
Grava dados/bench/carga.json (fora do git), o que a aba "Teste de carga" da área técnica mostra.

Não é carga de produção: é uma rodada pequena, com um worker, para ver a fila e os agentes se comportando.
"""

import http.cookiejar
import json
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
SAIDA = RAIZ / "dados" / "bench"
SENHA = "carga-local-123"
PERGUNTAS_PADRAO = [
    "Qual é o maior contrato da base e de qual fornecedor?",
    "Quantos contratos existem na base que você consegue consultar?",
    "Quantos contratos do Estado de Pernambuco existem na base?",
    "Quais fornecedores têm contrato com o Estado e com Garanhuns?",
    "Qual fornecedor tem mais ocorrências de sanção?",
    "Quanto o Estado pagou aos fornecedores com maior execução financeira?",
    "Quais contratos de Garanhuns têm processo licitatório informado?",
    "Qual é o contrato de maior valor de Garanhuns?",
]


class Sessao:
    """Um cliente HTTP com cookie e token CSRF, que conta requisições, tempo e erros 5xx."""

    def __init__(self, base: str, estatisticas: dict, trava: threading.Lock):
        self.base, self.est, self.trava = base, estatisticas, trava
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.csrf = ""

    def chamar(self, metodo: str, caminho: str, corpo: dict | None = None):
        dados = json.dumps(corpo).encode() if corpo is not None else None
        req = urllib.request.Request(self.base + "/api" + caminho, data=dados, method=metodo,
                                     headers={"Content-Type": "application/json", "X-CSRF-Token": self.csrf})
        inicio, status = time.monotonic(), 0
        try:
            with self.opener.open(req, timeout=60) as r:
                status, texto = r.status, r.read()
        except urllib.error.HTTPError as e:
            status, texto = e.code, e.read()
        except OSError:
            status, texto = 599, b"{}"
        with self.trava:
            self.est["requisicoes"] += 1
            self.est["tempos"].append(time.monotonic() - inicio)
            self.est["erros_500"] += status >= 500
        try:
            return status, json.loads(texto or b"{}")
        except ValueError:
            return status, {}

    def entrar(self, email: str, nome: str) -> bool:
        self.csrf = self.chamar("GET", "/me")[1].get("csrf", "")
        status, resp = self.chamar("POST", "/cadastro", {"nome": nome, "email": email, "senha": SENHA})
        if status == 409:   # já existe de uma rodada anterior
            status, resp = self.chamar("POST", "/login", {"email": email, "senha": SENHA})
        if status not in (200, 201):
            return False
        self.csrf = resp.get("csrf", self.csrf)
        if not resp.get("plano"):   # a tela do site faz isto logo depois do login (Api.garantirPlano)
            planos = self.chamar("GET", "/planos")[1]
            if not isinstance(planos, list) or not planos:
                return False
            padrao = sorted(planos, key=lambda p: (-len(p["tenants"]), -p["preco_mensal"]))[0]
            return self.chamar("POST", "/assinatura", {"plano_id": padrao["id"]})[0] in (200, 201)
        return True


def memoria_claude_mb() -> float | None:
    """Soma da memória dos processos `claude` (os agentes). None se não der para medir ou não houver nenhum."""
    try:
        if os.name == "nt":
            saida = subprocess.run(["tasklist", "/FO", "CSV", "/NH", "/FI", "IMAGENAME eq claude.exe"], capture_output=True, text=True, timeout=20).stdout
            kb = [int("".join(c for c in linha.rsplit('","', 1)[-1] if c.isdigit()) or 0) for linha in saida.splitlines() if linha.lower().startswith('"claude.exe"')]
        else:
            saida = subprocess.run(["ps", "-C", "claude", "-o", "rss="], capture_output=True, text=True, timeout=20).stdout
            kb = [int(x) for x in saida.split() if x.isdigit()]
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    return sum(kb) / 1024 if kb else 0.0


def perguntas(n: int) -> list[str]:
    gab = SAIDA / "gabarito.json"
    if gab.exists():
        fatos = [q["pergunta"] for q in json.loads(gab.read_text(encoding="utf-8")) if q["tipo"] == "fato" and q["perfil"] == "estado"]
        if len(fatos) >= n:
            return fatos[:n]
    return (PERGUNTAS_PADRAO * (n // len(PERGUNTAS_PADRAO) + 1))[:n]


def main() -> int:
    base = next((a for a in sys.argv[1:] if a.startswith("http")), "http://127.0.0.1:8080").rstrip("/")
    n = int(sys.argv[sys.argv.index("--pessoas") + 1]) if "--pessoas" in sys.argv else 8
    est = {"requisicoes": 0, "erros_500": 0, "tempos": []}
    trava = threading.Lock()

    # Contas prontas antes de largar: o cadastro não entra na medida.
    sessoes = []
    for i in range(1, n + 1):
        s = Sessao(base, est, trava)
        if not s.entrar(f"carga{i:02}@local.test", f"Pessoa {i}"):
            print(f"não consegui criar/entrar com carga{i:02}@local.test (o site está no ar? rodou o setup.php?)")
            return 1
        sessoes.append(s)
    est.update(requisicoes=0, erros_500=0, tempos=[])

    perg = perguntas(n)
    linhas = [None] * n
    largada = threading.Barrier(n + 1)
    medindo = threading.Event()
    medindo.set()
    pico = {"mb": 0.0}
    base_mb = memoria_claude_mb()

    def amostrar():
        while medindo.is_set():
            m = memoria_claude_mb()
            if m is not None:
                pico["mb"] = max(pico["mb"], m)
            time.sleep(0.7)

    def pessoa(i: int):
        s = sessoes[i]
        largada.wait()
        t0 = T0[0]
        status, resp = s.chamar("POST", "/perguntas", {"texto": perg[i]})
        linha = {"pessoa": f"Pessoa {i + 1}", "inicio": None, "primeiro": None, "total": None, "fontes": 0, "ok": False}
        linhas[i] = linha
        if status != 201:
            linha["erro"] = f"HTTP {status}"
            return
        pid, desde = resp["id"], 0
        while time.monotonic() - t0 < 300:
            status, r = s.chamar("GET", f"/perguntas/{pid}/eventos?desde={desde}")
            agora = time.monotonic() - t0
            if status == 200:
                if r.get("status") != "fila" and linha["inicio"] is None:
                    linha["inicio"] = agora
                for ev in r.get("eventos", []):
                    desde = max(desde, ev["seq"])
                    if linha["primeiro"] is None and ev["tipo"] in ("consulta", "texto"):
                        linha["primeiro"] = agora
                    linha["fontes"] += ev["tipo"] == "fonte"
                    if ev["tipo"] == "fim":
                        linha["ok"], linha["total"] = True, agora
                    elif ev["tipo"] == "erro":
                        linha["total"], linha["erro"] = agora, (ev.get("dados") or {}).get("motivo", "erro")
                if linha["total"] is not None or r.get("status") in ("concluida", "erro"):
                    linha["total"] = linha["total"] if linha["total"] is not None else agora
                    return
            time.sleep(0.5)
        linha["erro"] = "passou de 300 s"

    T0 = [0.0]
    fios = [threading.Thread(target=pessoa, args=(i,), daemon=True) for i in range(n)]
    for f in fios:
        f.start()
    amostrador = threading.Thread(target=amostrar, daemon=True)
    amostrador.start()
    T0[0] = time.monotonic()
    largada.wait()
    for f in fios:
        f.join()
    duracao = time.monotonic() - T0[0]
    medindo.clear()

    concluidas = sum(1 for l in linhas if l and l["ok"])
    for l in linhas:
        if l:
            print(l["pessoa"], "ok" if l["ok"] else "FALHOU " + str(l.get("erro", "")), "fila", l["inicio"] and round(l["inicio"], 1),
                  "total", l["total"] and round(l["total"], 1), "fontes", l["fontes"])
    r1 = lambda v: None if v is None else round(v, 1)  # noqa: E731
    saida = {
        "em": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "agentes_site": int(os.environ.get("AGENTES_SITE", "3")),
        "pessoas": n, "erros_usuario": n - concluidas, "duracao_s": r1(duracao),
        "latencia_media_s": round(sum(est["tempos"]) / max(len(est["tempos"]), 1), 2),
        "erros_500": est["erros_500"], "requisicoes": est["requisicoes"],
        "memoria_extra_mb": None if base_mb is None else round(max(pico["mb"] - base_mb, 0)),
        "linhas": [{"pessoa": l["pessoa"], "inicio": r1(l["inicio"]) or 0, "primeiro": r1(l["primeiro"]) or 0, "total": r1(l["total"]) or 0,
                    "fontes": l["fontes"]} for l in linhas if l],
    }
    SAIDA.mkdir(parents=True, exist_ok=True)
    (SAIDA / "carga.json").write_text(json.dumps(saida, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n{concluidas}/{n} respostas concluídas em {saida['duracao_s']} s; {saida['requisicoes']} requisições, "
          f"{saida['erros_500']} com erro 5xx; memória extra: {saida['memoria_extra_mb']} MB")
    return 0 if concluidas == n else 1


if __name__ == "__main__":
    sys.exit(main())
