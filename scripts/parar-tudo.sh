#!/usr/bin/env bash
# Desliga o site local, o gateway do WhatsApp e o worker. NÃO desliga o Docker nem os bancos e não apaga dado nenhum. Equivalente do parar-tudo.bat.
#
#   ./parar-tudo.sh                  desliga
#   ./parar-tudo.sh --simular        só mostra o que seria desligado
#   ./parar-tudo.sh --com-bancos     desliga também os bancos (os dados ficam guardados nos volumes)
#
# Só encerra processos DESTE projeto (gateway.ts, chat/worker.py e o php da porta 8080; onde há /proc, só os que estão em pastas do projeto).
# Manda SIGTERM (o gateway e o worker encerram de forma limpa) e só usa SIGKILL se, em 10 s, o processo não sair. Nunca usa sudo.
# Se o gateway estiver instalado como serviço (systemd --user: wa-gateway), ele é parado pelo systemctl, senão o Restart=always o religaria.
set -u

RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN="$RAIZ/logs/run"
SIMULAR=nao; COM_BANCOS=nao
for a in "$@"; do
  case "$a" in
    --simular) SIMULAR=sim ;;
    --com-bancos) COM_BANCOS=sim ;;
    *) echo "opção desconhecida: $a (use --simular ou --com-bancos)"; exit 2 ;;
  esac
done

if [ -t 1 ]; then V=$'\033[32m'; D=$'\033[90m'; C=$'\033[36m'; Z=$'\033[0m'; else V=; D=; C=; Z=; fi
tem() { command -v "$1" >/dev/null 2>&1; }

pids_de() {
  local padrao="$1" p
  tem pgrep || return 0
  for p in $(pgrep -f "$padrao" 2>/dev/null); do
    [ "$p" = "$$" ] && continue
    if [ -e "/proc/$p/cwd" ]; then readlink -f "/proc/$p/cwd" 2>/dev/null | grep -q "^$RAIZ" || continue; fi
    echo "$p"
  done
}

encerrar() {   # encerrar <pid> <quem>
  local pid="$1" quem="$2" i
  if [ "$SIMULAR" = sim ]; then printf '  [simulação] encerraria PID %-7s %s\n' "$pid" "$quem"; return; fi
  kill -TERM "$pid" 2>/dev/null
  for i in $(seq 1 20); do kill -0 "$pid" 2>/dev/null || break; sleep 0.5; done
  if kill -0 "$pid" 2>/dev/null; then kill -KILL "$pid" 2>/dev/null; printf '  %s[OK]%s forçado (SIGKILL) PID %-7s %s\n' "$V" "$Z" "$pid" "$quem"
  else printf '  %s[OK]%s encerrado PID %-7s %s\n' "$V" "$Z" "$pid" "$quem"; fi
}

achou=nao
if tem systemctl && systemctl --user is-active --quiet wa-gateway 2>/dev/null; then
  achou=sim
  if [ "$SIMULAR" = sim ]; then echo "  [simulação] pararia o serviço systemd --user wa-gateway"
  else systemctl --user stop wa-gateway && printf '  %s[OK]%s serviço wa-gateway parado\n' "$V" "$Z"; fi
fi
for item in 'gateway do WhatsApp|gateway\.ts' 'worker|chat/worker\.py' 'site local|php -S 127\.0\.0\.1:8080'; do
  quem="${item%%|*}"; padrao="${item#*|}"
  for pid in $(pids_de "$padrao"); do achou=sim; encerrar "$pid" "$quem"; done
done
[ "$achou" = nao ] && echo "Nada do projeto estava rodando."
tem pgrep || echo "(pgrep não encontrado: não consigo listar processos; instale procps)"

if [ "$SIMULAR" = nao ]; then
  rm -f "$RUN"/site.pid "$RUN"/gateway.pid "$RUN"/worker.pid "$RUN"/gateway.inicio 2>/dev/null
  if [ "$COM_BANCOS" = sim ]; then
    echo "Desligando os bancos (os dados ficam guardados nos volumes)..."
    ( cd "$RAIZ" && docker compose -f site/dev/docker-compose.yml stop >/dev/null 2>&1; docker compose --env-file .env -f infra/docker-compose.yml stop neo4j >/dev/null 2>&1 )
    printf '  %s[OK]%s bancos parados\n' "$V" "$Z"
  fi
  printf '%sPronto. Para ligar de novo: ./ligar-tudo.sh%s\n' "$C" "$Z"
fi
