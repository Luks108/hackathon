# Liga TUDO que o chat e o WhatsApp precisam, de uma vez, no Windows. Pode rodar de novo à vontade: só sobe o que ainda não está no ar.
#
#   Dois cliques em ligar-tudo.bat   (ou:  powershell -ExecutionPolicy Bypass -File scripts\ligar-tudo.ps1)
#   Só ver o que está no ar:           ... -Status
#
# O que sobe, nesta ordem:  1) Docker Desktop  2) bancos (MariaDB do site e Neo4j)  3) site local :8080  4) gateway do WhatsApp  5) worker
# Cada peça (3, 4 e 5) abre na própria janela, para você ver o log. Feche a janela para desligar só aquela peça, ou use parar-tudo.bat.
# Se o número do bot ainda não foi pareado, abre o pareamento (canal-whatsapp\parear.ps1), que pede o número na hora.
# Isto NÃO apaga dado nenhum, não mexe no .env e não imprime número de telefone.
param([switch]$Status)

$raiz = Split-Path $PSScriptRoot -Parent
$estado = $env:WHATSAPP_STATE_DIR
if (-not $estado) { $estado = Join-Path $env:USERPROFILE '.claude\channels\whatsapp-hackathon' }
$logs = Join-Path $raiz 'logs'
New-Item -ItemType Directory -Force $logs | Out-Null

function Ok($m)    { Write-Host "  [OK]    $m" -ForegroundColor Green }
function Info($m)  { Write-Host "  [..]    $m" -ForegroundColor Gray }
function Aviso($m) { Write-Host "  [AVISO] $m" -ForegroundColor Yellow }
function Erro($m)  { Write-Host "  [ERRO]  $m" -ForegroundColor Red }
function Titulo($m){ Write-Host "`n$m" -ForegroundColor Cyan }

# Processos de verdade (sem contar a janela do PowerShell que os lançou, que também traz o comando no texto).
function Achar($padrao) {
    @(Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match $padrao -and $_.Name -notmatch 'powershell|pwsh|cmd' -and $_.ProcessId -ne $PID })
}
function Site-No-Ar { try { (Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 'http://127.0.0.1:8080/api/saude').StatusCode -eq 200 } catch { $false } }
function Docker-No-Ar { docker info *> $null; $LASTEXITCODE -eq 0 }
function Saude($nome) { (docker inspect --format '{{.State.Health.Status}}' $nome 2>$null) }
function Pareado {
    $c = Join-Path $estado 'auth\creds.json'
    if (-not (Test-Path $c)) { return $false }
    try { return [bool]((Get-Content $c -Raw | ConvertFrom-Json).registered) } catch { return $false }
}
function Status-Do-Gateway {
    $f = Join-Path $estado 'status.json'
    if (-not (Test-Path $f)) { return $null }
    try { return (Get-Content $f -Raw | ConvertFrom-Json) } catch { return $null }
}
function Janela($titulo, $pasta, $comando) {
    Start-Process powershell -WorkingDirectory $pasta -ArgumentList '-NoExit', '-NoProfile', '-Command', "`$Host.UI.RawUI.WindowTitle='$titulo'; $comando"
}

# ------------------------------------------------------------------------------------------------------------------------
function Mostrar-Status {
    Titulo 'SITUAÇÃO AGORA'
    if (Docker-No-Ar) {
        Ok 'Docker Desktop ligado'
        foreach ($n in 'hackathon-site-db', 'hackathon-neo4j') {
            $s = Saude $n
            if ($s -eq 'healthy') { Ok "$n saudável" } else { Aviso "$n não está saudável (estado: $(if ($s) { $s } else { 'parado' }))" }
        }
    } else { Aviso 'Docker Desktop desligado' }
    if (Site-No-Ar) { Ok 'Site local no ar (http://127.0.0.1:8080)' } else { Aviso 'Site local fora do ar' }
    $g = @(Achar 'gateway\.ts')      # @(): com um só processo o PowerShell desenrola o resultado e .Count ficaria vazio
    $st = Status-Do-Gateway
    if ($g.Count -gt 0 -and $st -and $st.conectado -eq $true) { Ok 'Gateway do WhatsApp conectado' }
    elseif ($g.Count -gt 0) { Aviso 'Gateway rodando, mas ainda sem conexão com o WhatsApp' }
    else { Aviso 'Gateway do WhatsApp parado' }
    $w = @(Achar 'chat.worker\.py')
    if ($w.Count -gt 0) { Ok 'Worker rodando' } else { Aviso 'Worker parado' }
    if (-not (Pareado)) { Aviso 'O número do bot ainda NÃO foi pareado (rode canal-whatsapp\parear.ps1)' }
}

if ($Status) { Mostrar-Status; exit 0 }

Write-Host 'LIGANDO O AMBIENTE (pode rodar de novo: só sobe o que falta)' -ForegroundColor Cyan

# 1) Docker Desktop -----------------------------------------------------------------------------------------------------
Titulo '1/5  Docker'
if (-not (Docker-No-Ar)) {
    $exe = @("$env:ProgramFiles\Docker\Docker\Docker Desktop.exe", "$env:LOCALAPPDATA\Programs\DockerDesktop\Docker Desktop.exe",
             "$env:LOCALAPPDATA\Programs\Docker\Docker\Docker Desktop.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
    if (-not $exe) { Erro 'Não achei o Docker Desktop. Instale-o e rode de novo.'; exit 1 }
    Info 'Abrindo o Docker Desktop (pode levar até 2 minutos)...'
    Start-Process $exe
    for ($i = 0; $i -lt 60 -and -not (Docker-No-Ar); $i++) { Start-Sleep -Seconds 2 }
    if (-not (Docker-No-Ar)) { Erro 'O Docker não respondeu em 2 minutos. Abra o Docker Desktop, espere ele ficar verde e rode de novo.'; exit 1 }
}
Ok 'Docker Desktop ligado'

# 2) Bancos ---------------------------------------------------------------------------------------------------------------
Titulo '2/5  Bancos de dados'
Push-Location $raiz
docker compose -f site/dev/docker-compose.yml up -d 2>&1 | Out-Null
docker compose --env-file .env -f infra/docker-compose.yml up -d neo4j 2>&1 | Out-Null
Pop-Location
foreach ($n in 'hackathon-site-db', 'hackathon-neo4j') {
    for ($i = 0; $i -lt 45 -and (Saude $n) -ne 'healthy'; $i++) { Start-Sleep -Seconds 2 }
    if ((Saude $n) -eq 'healthy') { Ok "$n saudável" } else { Erro "$n não ficou saudável em 90 s (docker logs $n)"; exit 1 }
}

# 3) Site local ---------------------------------------------------------------------------------------------------------
Titulo '3/5  Site local'
if (Site-No-Ar) { Ok 'já estava no ar (http://127.0.0.1:8080)' }
else {
    Janela 'FornexIA - site :8080' $raiz 'php -S 127.0.0.1:8080 -t site/public_html site/dev/router.php'
    for ($i = 0; $i -lt 20 -and -not (Site-No-Ar); $i++) { Start-Sleep -Milliseconds 500 }
    if (Site-No-Ar) { Ok 'no ar (http://127.0.0.1:8080)' } else { Erro 'o site não subiu: veja a janela "FornexIA - site"'; }
}

# 4) Gateway do WhatsApp ------------------------------------------------------------------------------------------------
Titulo '4/5  Gateway do WhatsApp'
if (-not (Get-Command bun -ErrorAction SilentlyContinue)) { Aviso 'bun não está instalado: pulei o WhatsApp (powershell -c "irm bun.sh/install.ps1 | iex")' }
elseif (@(Achar 'gateway\.ts').Count -gt 0) { Ok 'já estava rodando' }
elseif (-not (Pareado)) {
    Aviso 'o número do bot ainda não foi pareado: abrindo o pareamento (ele pede o número na hora)'
    Janela 'FornexIA - parear WhatsApp' (Join-Path $raiz 'canal-whatsapp') '.\parear.ps1'
    Info 'Termine o pareamento na janela que abriu e rode este ligar-tudo de novo para subir o worker.'
}
else {
    $antes = Get-Date
    Remove-Item Env:\WA_PAIR_PHONE -ErrorAction SilentlyContinue
    # Fica na janela e também em logs\gateway.log (UTF-8), como o worker.
    $logG = Join-Path $raiz 'logs\gateway.log'
    $cmdG = "[Console]::OutputEncoding=[Text.Encoding]::UTF8; Set-Content '$logG' '' -Encoding utf8; " +
            "bun gateway.ts 2>&1 | ForEach-Object { `$_; Add-Content '$logG' `$_ -Encoding utf8 }"
    Janela 'FornexIA - gateway WhatsApp' (Join-Path $raiz 'canal-whatsapp') $cmdG
    $conectou = $false
    for ($i = 0; $i -lt 45 -and -not $conectou; $i++) {
        Start-Sleep -Seconds 2
        $s = Status-Do-Gateway
        # só vale um status ESCRITO depois de agora (um status antigo com conectado=true poderia enganar)
        if ($s -and $s.conectado -eq $true -and $s.atualizado -and ([DateTime]::Parse($s.atualizado).ToUniversalTime() -gt $antes.ToUniversalTime().AddSeconds(-2))) { $conectou = $true }
    }
    if ($conectou) { Ok 'conectado ao WhatsApp' } else { Aviso 'ainda sem conexão em 90 s: veja a janela "FornexIA - gateway WhatsApp"' }
}

# 5) Worker -------------------------------------------------------------------------------------------------------------
Titulo '5/5  Worker (responde o site e o WhatsApp)'
$w = @(Achar 'chat.worker\.py')
if ($w.Count -gt 0) { Ok 'já estava rodando' }
elseif (-not (Test-Path (Join-Path $raiz '.venv\Scripts\python.exe'))) { Erro 'não achei .venv\Scripts\python.exe (crie a .venv: guia, etapa 4)' }
else {
    # Fica na janela (para você ver) e também em logs\worker.log, em UTF-8. -u: sem atraso na saída.
    $cmd = "`$env:PYTHONIOENCODING='utf-8'; Set-Content logs\worker.log '' -Encoding utf8; " +
           ".\.venv\Scripts\python.exe -u chat\worker.py | ForEach-Object { `$_; Add-Content logs\worker.log `$_ -Encoding utf8 }"
    Janela 'FornexIA - worker' $raiz $cmd
    $no_ar = $false
    for ($i = 0; $i -lt 20 -and -not $no_ar; $i++) {
        Start-Sleep -Seconds 1
        $no_ar = (Test-Path (Join-Path $logs 'worker.log')) -and ((Get-Content (Join-Path $logs 'worker.log') -Raw -ErrorAction SilentlyContinue) -match 'worker no ar')
    }
    if ($no_ar) { Ok 'no ar' } else { Aviso 'não confirmei o "worker no ar": veja a janela "FornexIA - worker"' }
}

Mostrar-Status
Write-Host "`nPRONTO. Deixe as janelas abertas. Mande uma pergunta pelo WhatsApp ou abra http://127.0.0.1:8080/chat.html" -ForegroundColor Green
Write-Host 'Para desligar tudo: dois cliques em parar-tudo.bat (no PowerShell: .\parar-tudo.bat)' -ForegroundColor Gray
