# Liga o gateway do WhatsApp no Windows. Na primeira vez, pareia o número do bot por código (sem QR, sem câmera).
#
#   cd canal-whatsapp
#   .\parear.ps1
#
# O número do bot é digitado AGORA e fica só nesta janela: não vai para arquivo, para o .env nem para o histórico do PowerShell
# (Read-Host não grava histórico). Use um chip DEDICADO ao bot, nunca o número que você usa no dia a dia: o Baileys não é oficial e o
# WhatsApp pode banir o número. Depois de pareado, rode de novo para religar: ele não pergunta o número outra vez.
# Deixe esta janela aberta: fechar derruba o gateway (Ctrl+C encerra de forma limpa).

$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

if (-not (Get-Command bun -ErrorAction SilentlyContinue)) {
    Write-Host 'bun não está instalado. Instale com:  powershell -c "irm bun.sh/install.ps1 | iex"' -ForegroundColor Red
    exit 1
}
if (-not (Test-Path 'node_modules\@whiskeysockets\baileys')) {
    Write-Host 'Instalando as dependências (bun install)...'
    bun install
}

$ja = Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*gateway.ts*' -and $_.ProcessId -ne $PID }
if ($ja) {
    $pids = $ja.ProcessId -join ', '
    Write-Host "Já existe um gateway rodando (PID $pids). Só um processo pode ser dono do número. Feche o outro antes." -ForegroundColor Red
    exit 1
}

$estado = $env:WHATSAPP_STATE_DIR
if (-not $estado) { $estado = Join-Path $env:USERPROFILE '.claude\channels\whatsapp-hackathon' }
$creds = Join-Path $estado 'auth\creds.json'
$pareado = $false
if (Test-Path $creds) {
    try { $pareado = [bool]((Get-Content $creds -Raw | ConvertFrom-Json).registered) } catch { $pareado = $false }
}

if ($pareado) {
    Write-Host 'Número já pareado neste computador. Ligando o gateway...' -ForegroundColor Green
    Remove-Item Env:\WA_PAIR_PHONE -ErrorAction SilentlyContinue
} else {
    Write-Host 'PAREAMENTO. No celular do bot, deixe o WhatsApp aberto.' -ForegroundColor Cyan
    $n = (Read-Host 'Número do bot (55 + DDD + número, só dígitos)') -replace '\D', ''
    if ($n -notmatch '^55\d{10,11}$') {
        Write-Host 'Número inválido. Use 55 + DDD + número, só dígitos (12 ou 13 dígitos).' -ForegroundColor Red
        exit 1
    }
    $env:WA_PAIR_PHONE = $n          # só neste processo; some quando a janela fechar
    Write-Host ''
    Write-Host 'Quando aparecer "CÓDIGO DE PAREAMENTO: XXXXXXXX", no celular: WhatsApp > Aparelhos conectados > Conectar um aparelho >' -ForegroundColor Yellow
    Write-Host 'Conectar com número de telefone > digite o código. Você tem cerca de 1 minuto.' -ForegroundColor Yellow
    Write-Host ''
}

try {
    bun gateway.ts
} finally {
    Remove-Item Env:\WA_PAIR_PHONE -ErrorAction SilentlyContinue
}
