"""Lê os logs por subsistema (logs/*.jsonl) e conta o que aconteceu. Só lê: nunca altera nem apaga nada.

    python scripts/jornada.py wa:3EB0A49AA2B2        # a jornada inteira de UMA pergunta, de todos os arquivos, em ordem de horário
    python scripts/jornada.py --ultimas [N]          # os N últimos desfechos (padrão 15): respondeu ou não, motivo, tempo, modelo
    python scripts/jornada.py --falhas [N]           # só as que NÃO foram respondidas, com o motivo classificado e o detalhe
    python scripts/jornada.py --seguranca [N]        # tentativas de ataque, entradas bloqueadas, ferramentas negadas, CPF mascarado
    python scripts/jornada.py --saude [N]            # quedas e voltas de cada peça, com a duração
    python scripts/jornada.py --pasta OUTRA          # logs em outra pasta (padrão: FORNEXIA_LOGS_DIR ou logs/)

O request_id aparece em cada linha de cada arquivo: `wa:<id da mensagem>` no WhatsApp, `site:<id da pergunta>` no site.
Para achar o id de uma pergunta recente, use --ultimas.
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
ORDEM_DOS_ARQUIVOS = ("gateway", "worker", "agente", "ferramentas", "seguranca", "saude")
IGNORAR_NA_TELA = {"ts", "nivel", "subsistema", "evento", "request_id"}


def pasta_padrao() -> Path:
    return Path(os.environ.get("FORNEXIA_LOGS_DIR") or RAIZ / "logs")


def carregar(pasta: Path) -> list[dict]:
    """Todas as linhas válidas de logs/<subsistema>.jsonl e das cópias giradas (.1, .2, ...), em ordem de horário."""
    linhas = []
    for sub in ORDEM_DOS_ARQUIVOS:
        for arq in sorted(pasta.glob(f"{sub}.jsonl*")):
            try:
                for texto in arq.read_text(encoding="utf-8", errors="replace").splitlines():
                    try:
                        d = json.loads(texto)
                    except ValueError:
                        continue
                    if isinstance(d, dict) and "ts" in d:
                        linhas.append(d)
            except OSError:
                continue

    def chave(d):
        try:
            return datetime.fromisoformat(d["ts"]).timestamp()
        except (ValueError, TypeError):
            return 0.0
    return sorted(linhas, key=chave)       # estável: no mesmo instante, a ordem dos arquivos acima


def _hora(ts: str) -> str:
    return str(ts)[11:23] if len(str(ts)) >= 23 else str(ts)


def _campos(d: dict) -> str:
    partes = []
    for k, v in d.items():
        if k in IGNORAR_NA_TELA or v is None:
            continue
        partes.append(f"{k}={json.dumps(v, ensure_ascii=False) if not isinstance(v, str) else v}")
    return " ".join(partes)


def jornada(linhas: list[dict], request_id: str) -> list[str]:
    achadas = [d for d in linhas if d.get("request_id") == request_id]
    saida = [f"{_hora(d['ts'])}  {d['nivel']:<5}  {d['subsistema']:<11} {d['evento']:<30} {_campos(d)}" for d in achadas]
    return saida or [f"Nenhuma linha com request_id {request_id!r}. Use --ultimas para ver os ids recentes."]


def _tabela_de_desfechos(desfechos: list[dict]) -> list[str]:
    cab = f"{'hora':<12} {'request_id':<24} {'canal':<9} {'ok':<4} {'motivo':<11} {'ms':>6}  modelo"
    linhas = [cab]
    for d in desfechos:
        linhas.append(f"{_hora(d['ts']):<12} {str(d.get('request_id', '-')):<24} {str(d.get('canal', '-')):<9} {'sim' if d.get('respondeu') else 'NÃO':<4} "
                      f"{str(d.get('motivo') or '-'):<11} {d.get('duracao_ms', '-'):>6}  {d.get('modelo') or '-'}")
    return linhas


def desfechos(linhas: list[dict], so_falhas: bool = False) -> list[dict]:
    d = [x for x in linhas if x.get("subsistema") == "worker" and x.get("evento") == "desfecho"]
    return [x for x in d if x.get("respondeu") is False and x.get("motivo")] if so_falhas else d


def resumo_de_falhas(falhas: list[dict]) -> list[str]:
    por = {}
    for d in falhas:
        por[d["motivo"]] = por.get(d["motivo"], 0) + 1
    return ["Falhas por motivo: " + ", ".join(f"{m}={n}" for m, n in sorted(por.items(), key=lambda x: -x[1]))] if por else ["Nenhuma falha registrada."]


def main(argv: list[str]) -> int:
    pasta = pasta_padrao()
    if "--pasta" in argv:
        i = argv.index("--pasta")
        pasta = Path(argv[i + 1])
        argv = argv[:i] + argv[i + 2:]
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    linhas = carregar(pasta)
    if not linhas:
        print(f"Nenhum log em {pasta}. (Os logs só passam a existir depois que o worker, o gateway e o vigia sobem com esta versão.)")
        return 1
    n = int(argv[1]) if len(argv) > 1 and argv[1].isdigit() else 15
    if argv[0] == "--ultimas":
        print("\n".join(_tabela_de_desfechos(desfechos(linhas)[-n:])))
    elif argv[0] == "--falhas":
        falhas = desfechos(linhas, so_falhas=True)
        print("\n".join(_tabela_de_desfechos(falhas[-n:])))
        for d in falhas[-n:]:
            print(f"  {d['request_id']}: {d.get('detalhe') or '(sem detalhe)'}")
        print("\n".join(resumo_de_falhas(falhas)))
    elif argv[0] == "--seguranca":
        for d in [x for x in linhas if x.get("subsistema") == "seguranca"][-n:]:
            print(f"{_hora(d['ts'])}  {d['nivel']:<5}  {d['evento']:<28} {d.get('request_id', '-'):<22} {_campos(d)}")
    elif argv[0] == "--saude":
        for d in [x for x in linhas if x.get("subsistema") == "saude"][-n:]:
            print(f"{d['ts'][:23]}  {d['nivel']:<5}  {d['evento']:<32} {_campos(d)}")
    else:
        print("\n".join(jornada(linhas, argv[0])))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
