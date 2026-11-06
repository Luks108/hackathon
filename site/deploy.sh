#!/usr/bin/env bash
# Sobe o site para hackathon.figueiredo.dev em ~10s. Uso: ./site/deploy.sh [--setup]
#   --setup  cria/atualiza as tabelas e o admin (rode na primeira vez e após mudar o schema)
set -euo pipefail
RAIZ="$(cd "$(dirname "$0")/.." && pwd)"
set -a; source "$RAIZ/.env"; set +a
SSH="ssh -i ${HOSTINGER_SSH_KEY/#\~/$HOME} -p $HOSTINGER_PORT -o BatchMode=yes"
ALVO="$HOSTINGER_USER@$HOSTINGER_HOST"
DOMINIO_DIR="/home/$HOSTINGER_USER/domains/$SITE"

# Config com segredos: gerada aqui, gravada fora do public_html, nunca versionada.
$SSH "$ALVO" "umask 077; cat > $DOMINIO_DIR/hackathon-config.php" <<PHP
<?php
const DB_HOST = '$DB_HOST';
const DB_NAME = '$DB_NAME';
const DB_USER = '$DB_USER';
const DB_PASS = '$DB_PASS';
const API_KEY = '$API_KEY';
const INFERENCIA_URL = '$INFERENCIA_URL';
PHP

rsync -az --delete --include 'uploads/.htaccess' --exclude 'uploads/*' -e "$SSH" "$RAIZ/site/public_html/" "$ALVO:$DOMINIO_DIR/public_html/"
rsync -az -e "$SSH" "$RAIZ/site/setup.php" "$ALVO:$DOMINIO_DIR/setup.php"
$SSH "$ALVO" "mkdir -p $DOMINIO_DIR/public_html/uploads && rm -f $DOMINIO_DIR/public_html/default.php"

if [[ "${1:-}" == "--setup" ]]; then
  $SSH "$ALVO" "php $DOMINIO_DIR/setup.php '$ADMIN_EMAIL' 'Admin' '$ADMIN_SENHA'"
fi
echo "ok → https://$SITE"
