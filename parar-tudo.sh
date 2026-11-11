#!/usr/bin/env bash
# Atalho: desliga site, gateway do WhatsApp e worker (não desliga o Docker nem apaga dado). Veja scripts/parar-tudo.sh.
exec bash "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/scripts/parar-tudo.sh" "$@"
