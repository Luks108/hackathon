#!/usr/bin/env bash
# Liga TUDO que o chat e o WhatsApp precisam, de uma vez, no Linux (e no macOS). Equivalente do ligar-tudo.bat do Windows.
# Pode rodar de novo à vontade: só sobe o que ainda não está no ar.
#
#   ./ligar-tudo.sh            liga tudo
#   ./ligar-tudo.sh --status   só mostra o que está no ar
#
# O que sobe, nesta ordem:  1) Docker (precisa já estar ligado)  2) bancos (MariaDB do site e Neo4j)  3) site local :8080
#                           4) gateway do WhatsApp (bun)  5) worker (por último, porque só ele atende o que chega depois de ligado)
# Cada peça roda em segundo plano, separada do terminal (fechar o terminal NÃO as derruba), com log em logs/site.log, logs/gateway.log
# e logs/worker.log e o PID em logs/run/. Para desligar: ./parar-tudo.sh.
# Se o número do bot ainda não foi pareado, avisa para rodar canal-whatsapp/parear.sh (ele pede o número na hora; não dá para fazer em segundo plano).
# NÃO apaga dado, não mexe no .env e não imprime número de telefone. Nunca usa sudo.
set -u

RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ESTADO="${WHATSAPP_STATE_DIR:-$HOME/.claude/channels/whatsapp-hackathon}"
LOGS="$RAIZ/logs"
RUN="$LOGS/run"
mkdir -p "$RUN"
ESPERA="${LIGAR_TEMPO_MAX:-90}"      # segundos de espera por peça (bancos, gateway, worker); os testes usam menos
SO_STATUS=nao
[ "${1:-}" = "--status" ] && SO_STATUS=sim

if [ -t 1 ]; then V=$'\033[32m'; A=$'\033[33m'; R=$'\033[31m'; C=$'\033[36m'; D=$'\033[90m'; Z=$'\033[0m'; else V=; A=; R=; C=; D=; Z=; fi
ok()     { printf '  %s[OK]%s    %s\n' "$V" "$Z" "$*"; }
info()   { printf '  %s[..]%s    %s\n' "$D" "$Z" "$*"; }
aviso()  { printf '  %s[AVISO]%s %s\n' "$A" "$Z" "$*"; }
erro()   { printf '  %s[ERRO]%s  %s\n' "$R" "$Z" "$*"; }
titulo() { printf '\n%s%s%s\n' "$C" "$*" "$Z"; }
tem()    { command -v "$1" >/dev/null 2>&1; }

# PIDs de processos DESTE projeto cuja linha de comando casa com o padrão (regex). Onde há /proc, confere que o diretório do processo é do projeto.
pids_de() {
  local padrao="$1" p
  tem pgrep || return 0
  for p in $(pgrep -f "$padrao" 2>/dev/null); do
    [ "$p" = "$$" ] && continue
    if [ -e "/proc/$p/cwd" ]; then readlink -f "/proc/$p/cwd" 2>/dev/null | grep -q "^$RAIZ" || continue; fi
    echo "$p"
  done
}
rodando() { [ -n "$(pids_de "$1")" ]; }

http_ok() {
  if tem curl; then curl -fsS -m 2 "$1" >/dev/null 2>&1; return $?; fi
  python3 -c "import sys,urllib.request; urllib.request.urlopen(sys.argv[1], timeout=2)" "$1" >/dev/null 2>&1
}
site_no_ar()    { http_ok "http://127.0.0.1:8080/api/saude"; }
docker_no_ar()  { tem docker && docker info >/dev/null 2>&1; }
saude()         { docker inspect --format '{{.State.Health.Status}}' "$1" 2>/dev/null; }
pareado()       { [ -f "$ESTADO/auth/creds.json" ] && grep -Eq '"registered" *: *true' "$ESTADO/auth/creds.json"; }
gateway_conectado() { [ -f "$ESTADO/status.json" ] && grep -Eq '"conectado" *: *true' "$ESTADO/status.json"; }
servico_do_gateway() { tem systemctl && systemctl --user is-active --quiet wa-gateway 2>/dev/null; }
gateway_rodando() { rodando 'gateway\.ts' || servico_do_gateway; }

python_do_projeto() {
  if [ -x "$RAIZ/.venv/bin/python" ]; then echo "$RAIZ/.venv/bin/python"; elif tem python3; then command -v python3; fi
}

# Roda em segundo plano, fora do terminal. iniciar <nome> <pasta> <comando...>
iniciar() {
  local nome="$1" dir="$2"; shift 2
  (
    cd "$dir" || exit 1
    if tem setsid; then setsid nohup "$@" >>"$LOGS/$nome.log" 2>&1 </dev/null &
    else nohup "$@" >>"$LOGS/$nome.log" 2>&1 </dev/null &
    fi
    echo $! >"$RUN/$nome.pid"
  )
}

mostrar_status() {
  titulo "SITUAÇÃO AGORA"
  if docker_no_ar; then
    ok "Docker ligado"
    local n s
    for n in hackathon-site-db hackathon-neo4j; do
      s="$(saude "$n")"
      if [ "$s" = "healthy" ]; then ok "$n saudável"; else aviso "$n não está saudável (estado: ${s:-parado})"; fi
    done
  else aviso "Docker desligado (ou sem permissão: seu usuário está no grupo docker?)"; fi
  if site_no_ar; then ok "Site local no ar (http://127.0.0.1:8080)"; else aviso "Site local fora do ar"; fi
  if gateway_rodando; then
    if gateway_conectado; then ok "Gateway do WhatsApp conectado"; else aviso "Gateway rodando, mas ainda sem conexão com o WhatsApp"; fi
  else aviso "Gateway do WhatsApp parado"; fi
  if rodando 'chat/worker\.py'; then ok "Worker rodando"; else aviso "Worker parado"; fi
  if rodando 'chat/vigia\.py'; then ok "Vigia de saúde rodando (logs/saude.jsonl)"; else aviso "Vigia de saúde parado"; fi
  pareado || aviso "O número do bot ainda NÃO foi pareado (rode canal-whatsapp/parear.sh)"
  tem pgrep || aviso "pgrep não encontrado: não consigo ver os processos (instale procps)"
}

if [ "$SO_STATUS" = sim ]; then mostrar_status; exit 0; fi

printf '%sLIGANDO O AMBIENTE (pode rodar de novo: só sobe o que falta)%s\n' "$C" "$Z"

# 1) Docker -------------------------------------------------------------------------------------------------------------
titulo "1/5  Docker"
if ! docker_no_ar; then
  erro "O Docker não está respondendo."
  info "Linux: sudo systemctl start docker   (e seu usuário precisa estar no grupo docker: sudo usermod -aG docker \$USER, depois sair e entrar)"
  info "Docker Desktop: abra o aplicativo e espere ficar verde."
  exit 1
fi
ok "Docker ligado"

# 2) Bancos -------------------------------------------------------------------------------------------------------------
titulo "2/5  Bancos de dados"
( cd "$RAIZ" && docker compose -f site/dev/docker-compose.yml up -d >/dev/null 2>&1; docker compose --env-file .env -f infra/docker-compose.yml up -d neo4j >/dev/null 2>&1 )
for n in hackathon-site-db hackathon-neo4j; do
  for _ in $(seq 1 $((ESPERA / 2))); do [ "$(saude "$n")" = "healthy" ] && break; sleep 2; done
  if [ "$(saude "$n")" = "healthy" ]; then ok "$n saudável"; else erro "$n não ficou saudável em ${ESPERA} s (docker logs $n)"; exit 1; fi
done

# 3) Site local ---------------------------------------------------------------------------------------------------------
titulo "3/5  Site local"
if site_no_ar; then ok "já estava no ar (http://127.0.0.1:8080)"
elif ! tem php; then aviso "php não está instalado: não subi o site (apt install php-cli php-mysql)"
else
  iniciar site "$RAIZ" php -S 127.0.0.1:8080 -t site/public_html site/dev/router.php
  for _ in $(seq 1 20); do site_no_ar && break; sleep 0.5; done
  if site_no_ar; then ok "no ar (http://127.0.0.1:8080)"; else erro "o site não subiu: veja logs/site.log"; fi
fi

# 4) Gateway do WhatsApp ------------------------------------------------------------------------------------------------
titulo "4/5  Gateway do WhatsApp"
if ! tem bun && ! servico_do_gateway; then aviso "bun não está instalado: pulei o WhatsApp (curl -fsSL https://bun.sh/install | bash)"
elif gateway_rodando; then ok "já estava rodando"
elif ! pareado; then
  aviso "o número do bot ainda não foi pareado."
  info "Rode, num terminal seu:  canal-whatsapp/parear.sh   (ele pede o número na hora e deixa o gateway rodando nesse terminal)."
  info "Depois rode este ligar-tudo de novo para subir o worker."
else
  marca="$RUN/gateway.inicio"; : >"$marca"; sleep 1
  unset WA_PAIR_PHONE
  iniciar gateway "$RAIZ/canal-whatsapp" bun gateway.ts
  conectou=nao
  for _ in $(seq 1 $((ESPERA / 2))); do
    sleep 2
    # só vale um status ESCRITO depois de agora (um status antigo com conectado=true poderia enganar)
    if [ "$ESTADO/status.json" -nt "$marca" ] && gateway_conectado; then conectou=sim; break; fi
  done
  if [ "$conectou" = sim ]; then ok "conectado ao WhatsApp"; else aviso "ainda sem conexão em ${ESPERA} s: veja logs/gateway.log"; fi
fi

# 5) Worker -------------------------------------------------------------------------------------------------------------
titulo "5/5  Worker (responde o site e o WhatsApp)"
if rodando 'chat/worker\.py'; then ok "já estava rodando"
else
  PY="$(python_do_projeto)"
  if [ -z "$PY" ]; then erro "não achei .venv/bin/python nem python3 (crie a .venv: guia, etapa 4)"
  else
    : >"$LOGS/worker.log"
    PYTHONIOENCODING=utf-8 iniciar worker "$RAIZ" "$PY" -u chat/worker.py
    no_ar=nao
    for _ in $(seq 1 $((ESPERA / 4 + 1))); do sleep 1; if grep -q 'worker no ar' "$LOGS/worker.log" 2>/dev/null; then no_ar=sim; break; fi; done
    if [ "$no_ar" = sim ]; then ok "no ar"; else aviso "não confirmei o \"worker no ar\": veja logs/worker.log"; fi
  fi
fi

# Vigia de saúde (não bloqueia nada): grava em logs/saude.jsonl quando uma peça cai e quando volta, com a duração da queda.
if rodando 'chat/vigia\.py'; then ok "vigia de saúde já rodando"
else
  PYV="$(python_do_projeto)"
  if [ -n "$PYV" ]; then
    : >"$LOGS/vigia.log"
    PYTHONIOENCODING=utf-8 iniciar vigia "$RAIZ" "$PYV" -u chat/vigia.py
    sleep 1
    ok "vigia de saúde no ar (logs/saude.jsonl)"
  else aviso "vigia de saúde não iniciado: sem python"; fi
fi

mostrar_status
printf '\n%sPRONTO.%s Mande uma pergunta pelo WhatsApp ou abra http://127.0.0.1:8080/chat.html\n' "$V" "$Z"
printf '%sPara ver o que está acontecendo: tail -f logs/worker.log   |   para desligar: ./parar-tudo.sh%s\n' "$D" "$Z"
