#!/usr/bin/env bash
# Liga o gateway do WhatsApp no Linux/macOS. Na primeira vez, pareia o número do bot por código (sem QR, sem câmera).
#
#   cd canal-whatsapp && ./parear.sh
#
# O número é digitado AGORA e fica só neste processo: não vai para arquivo, .env nem histórico do shell (read -r não grava histórico).
# Use um chip DEDICADO ao bot: o Baileys não é oficial e o WhatsApp pode banir o número. Depois de pareado, rode de novo para religar.
# Para deixar ligado em segundo plano, use o serviço systemd (wa-gateway.service) depois do primeiro pareamento.
set -euo pipefail
cd "$(dirname "$0")"

command -v bun >/dev/null || { echo 'bun não está instalado: curl -fsSL https://bun.sh/install | bash'; exit 1; }
[ -d node_modules/@whiskeysockets/baileys ] || { echo 'Instalando as dependências (bun install)...'; bun install; }
if pgrep -f 'gateway.ts' >/dev/null; then
  echo 'Já existe um gateway rodando. Só um processo pode ser dono do número. Feche o outro antes.'; exit 1
fi

estado="${WHATSAPP_STATE_DIR:-$HOME/.claude/channels/whatsapp-hackathon}"
pareado=nao
if [ -f "$estado/auth/creds.json" ] && grep -q '"registered": *true' "$estado/auth/creds.json"; then pareado=sim; fi

if [ "$pareado" = sim ]; then
  echo 'Número já pareado neste computador. Ligando o gateway...'
  unset WA_PAIR_PHONE
else
  echo 'PAREAMENTO. No celular do bot, deixe o WhatsApp aberto.'
  read -r -p 'Número do bot (55 + DDD + número, só dígitos): ' n
  n="${n//[^0-9]/}"
  [[ "$n" =~ ^55[0-9]{10,11}$ ]] || { echo 'Número inválido. Use 55 + DDD + número, só dígitos (12 ou 13 dígitos).'; exit 1; }
  export WA_PAIR_PHONE="$n"
  echo
  echo 'Quando aparecer "CÓDIGO DE PAREAMENTO: XXXXXXXX", no celular: WhatsApp > Aparelhos conectados > Conectar um aparelho >'
  echo 'Conectar com número de telefone > digite o código. Você tem cerca de 1 minuto.'
  echo
fi
exec bun gateway.ts
