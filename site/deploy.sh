#!/usr/bin/env bash
# Sobe o site para hackathon.figueiredo.dev em ~10s. Uso: ./site/deploy.sh [--setup]
#   --setup  cria/atualiza as tabelas, os planos e o admin (rode na primeira vez e após mudar o schema)
#
# Precisa no .env: HOSTINGER_*, SITE, DB_HOST, DB_NAME, DB_USER, DB_PASS, WORKER_KEY (24+ caracteres),
# e ADMIN_EMAIL e ADMIN_SENHA para o --setup. DB_PORT é opcional.
set -euo pipefail
RAIZ="$(cd "$(dirname "$0")/.." && pwd)"
set -a; source "$RAIZ/.env"; set +a

: "${WORKER_KEY:?defina WORKER_KEY no .env (mínimo 24 caracteres)}"
if [[ ${#WORKER_KEY} -lt 24 ]]; then echo "WORKER_KEY precisa ter pelo menos 24 caracteres" >&2; exit 1; fi

SSH="ssh -i ${HOSTINGER_SSH_KEY/#\~/$HOME} -p $HOSTINGER_PORT -o BatchMode=yes"
ALVO="$HOSTINGER_USER@$HOSTINGER_HOST"
DOMINIO_DIR="/home/$HOSTINGER_USER/domains/$SITE"

# Texto seguro dentro de uma string PHP entre aspas simples: escapa a barra invertida e a aspa simples.
# Sem isto, uma senha com ' quebrava o arquivo de configuração (ou injetava código nele).
php_str() { printf '%s' "$1" | sed -e 's/\\/\\\\/g' -e "s/'/\\\\'/g"; }

# Config com segredos: gerada aqui, gravada fora do public_html, nunca versionada.
$SSH "$ALVO" "umask 077; cat > $DOMINIO_DIR/hackathon-config.php" <<PHP
<?php
const AMBIENTE = 'prod';
const DB_HOST = '$(php_str "$DB_HOST")';
$( [[ -n "${DB_PORT:-}" ]] && echo "const DB_PORT = $((DB_PORT));" )
const DB_NAME = '$(php_str "$DB_NAME")';
const DB_USER = '$(php_str "$DB_USER")';
const DB_PASS = '$(php_str "$DB_PASS")';
const WORKER_KEY = '$(php_str "$WORKER_KEY")';
PHP

rsync -az --delete -e "$SSH" "$RAIZ/site/public_html/" "$ALVO:$DOMINIO_DIR/public_html/"
rsync -az -e "$SSH" "$RAIZ/site/setup.php" "$ALVO:$DOMINIO_DIR/setup.php"
$SSH "$ALVO" "rm -f $DOMINIO_DIR/public_html/default.php"

if [[ "${1:-}" == "--setup" ]]; then
  # printf %q protege o texto para o shell do servidor (aspas, espaços, $ e outros).
  $SSH "$ALVO" "php $DOMINIO_DIR/setup.php $(printf '%q' "$ADMIN_EMAIL") Admin $(printf '%q' "$ADMIN_SENHA")"
fi
echo "ok → https://$SITE"
