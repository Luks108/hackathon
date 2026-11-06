"""Worker de mentira: responde às perguntas da fila com um roteiro fixo, sem agente nem Neo4j.

Serve para desenvolver e testar o site (e o chatbox) antes de o worker real existir. Usa as mesmas rotas que o
worker real vai usar, então é também um exemplo do contrato.

    python site/dev/worker_falso.py [--url http://127.0.0.1:8080]

Palavras na pergunta mudam o roteiro:
    "erro"   termina com um evento de erro
    "lento"  fica sem responder (para testar o limite de tempo)
    "sem fonte"  responde sem citar fonte
Variáveis: API_BASE, WORKER_KEY (senão lê de site/hackathon-config.php), ATRASO (segundos entre eventos).
"""

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
BASE = os.environ.get("API_BASE", "http://127.0.0.1:8080")
if "--url" in sys.argv:
    BASE = sys.argv[sys.argv.index("--url") + 1]
KEY = os.environ.get("WORKER_KEY") or re.search(r"const WORKER_KEY = '([^']+)'", (RAIZ / "site/hackathon-config.php").read_text(encoding="utf-8")).group(1)
ATRASO = float(os.environ.get("ATRASO", "0.15"))


def api(metodo, caminho, corpo=None):
    req = urllib.request.Request(BASE + caminho, method=metodo, data=json.dumps(corpo).encode() if corpo is not None else None,
                                 headers={"X-Worker-Key": KEY, "Content-Type": "application/json"})
    try:
        r = urllib.request.urlopen(req, timeout=20)
    except urllib.error.HTTPError as e:
        r = e
    texto = r.read().decode("utf-8")
    return r.status if hasattr(r, "status") else r.code, (json.loads(texto) if texto else None)


class Enviador:
    def __init__(self, pergunta_id):
        self.id, self.seq = pergunta_id, 0

    def enviar(self, tipo, dados=None):
        self.seq += 1
        status, corpo = api("POST", f"/api/worker/perguntas/{self.id}/eventos", {"eventos": [{"seq": self.seq, "tipo": tipo, "dados": dados or {}}]})
        if status == 409:   # o site já encerrou esta pergunta (por tempo)
            raise StopIteration
        if status != 200:
            raise RuntimeError(f"{status} {corpo}")
        time.sleep(ATRASO)


def responder(p):
    texto = p["texto"].lower()
    e = Enviador(p["id"])
    try:
        e.enviar("consulta", {"nome": "cobertura"})
        if "lento" in texto:
            time.sleep(300)
            return
        e.enviar("consulta", {"nome": "buscar_fornecedor"})
        if "erro" in texto:
            e.enviar("erro", {"motivo": "Não consegui consultar a base agora. Tente novamente em instantes."})
            return
        e.enviar("consulta", {"nome": "contratos_do_fornecedor"})
        resposta = ("Encontrei 1 contrato da Construtora Exemplo Ltda em Garanhuns: nº 1/2026, reforma de escola, "
                    "valor contratado de R$ 120.000,00.\n")
        if "pe-estado" in p["tenants"]:
            e.enviar("consulta", {"nome": "sancoes_do_fornecedor"})
            resposta += "No cadastro de sanções do Estado há 1 ocorrência em aberto. Sanção em aberto não prova irregularidade."
        else:
            resposta += "O cadastro de sanções do Estado está fora do seu plano, então não foi consultado."
        for palavra in resposta.split(" "):
            e.enviar("texto", {"delta": palavra + " "})
        if "sem fonte" not in texto:
            e.enviar("fonte", {"evidencia": "g1", "capturado_em": "2026-11-05", "url": "https://exemplo.invalid/fonte",
                               "trecho": "DADO FICTÍCIO. Contrato 1/2026, Construtora Exemplo, reforma de escola, R$ 120.000,00"})
            if "pe-estado" in p["tenants"]:
                e.enviar("fonte", {"evidencia": "e1", "capturado_em": "2026-11-05", "url": "javascript:alert(1)",
                                   "trecho": "DADO FICTÍCIO. MULTA, EM ABERTO, Construtora Exemplo"})
        e.enviar("fim", {})
    except StopIteration:
        print(f"  pergunta {p['id']}: encerrada pelo site, parei")


def main():
    print(f"worker falso em {BASE}, atraso {ATRASO}s. Ctrl+C para parar.")
    while True:
        try:
            status, p = api("POST", "/api/worker/proxima")
        except Exception as erro:  # noqa: BLE001
            print("sem conexão:", erro)
            time.sleep(2)
            continue
        if status == 200:
            print(f"pergunta {p['id']} ({','.join(p['tenants'])}): {p['texto'][:60]!r}")
            responder(p)
        elif status == 204:
            time.sleep(0.5)
        else:
            print("resposta inesperada:", status, p)
            time.sleep(2)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
