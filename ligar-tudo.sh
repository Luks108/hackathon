#!/usr/bin/env bash
# Atalho: liga Docker (já ligado), bancos, site, gateway do WhatsApp e worker. Veja scripts/ligar-tudo.sh.
exec bash "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/scripts/ligar-tudo.sh" "$@"
