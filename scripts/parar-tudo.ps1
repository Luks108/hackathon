# Desliga o site local, o gateway do WhatsApp e o worker (e as janelas deles). NÃO desliga o Docker nem os bancos, e não apaga dado nenhum.
#
#   Dois cliques em parar-tudo.bat   (ou:  powershell -ExecutionPolicy Bypass -File scripts\parar-tudo.ps1)
#   Só ver o que seria desligado:      ... -Simular
#   Desligar também os bancos:         ... -ComBancos
#
# Só encerra processos do projeto: o gateway (gateway.ts), o worker (chat\worker.py), o site (php na porta 8080) e as janelas que o
# ligar-tudo abriu (título "FornexIA - ..."). Nenhum outro PowerShell, PHP ou Python seu é tocado.
param([switch]$Simular, [switch]$ComBancos)

$raiz = Split-Path $PSScriptRoot -Parent
$estado = $env:WHATSAPP_STATE_DIR
if (-not $estado) { $estado = Join-Path $env:USERPROFILE '.claude\channels\whatsapp-hackathon' }

$todos = Get-CimInstance Win32_Process | Where-Object { $_.ProcessId -ne $PID }
$alvos = @()
$alvos += $todos | Where-Object { $_.Name -notmatch 'powershell|pwsh|cmd' -and $_.CommandLine -match 'gateway\.ts' }           | ForEach-Object { [pscustomobject]@{ Pid = $_.ProcessId; Quem = 'gateway do WhatsApp' } }
$alvos += $todos | Where-Object { $_.Name -notmatch 'powershell|pwsh|cmd' -and $_.CommandLine -match 'chat.worker\.py' }        | ForEach-Object { [pscustomobject]@{ Pid = $_.ProcessId; Quem = 'worker' } }
$alvos += $todos | Where-Object { $_.Name -notmatch 'powershell|pwsh|cmd' -and $_.CommandLine -match 'chat.vigia\.py' }         | ForEach-Object { [pscustomobject]@{ Pid = $_.ProcessId; Quem = 'vigia de saúde' } }
$alvos += $todos | Where-Object { $_.Name -match '^php' -and $_.CommandLine -match '127\.0\.0\.1:8080' }                          | ForEach-Object { [pscustomobject]@{ Pid = $_.ProcessId; Quem = 'site local' } }
$alvos += $todos | Where-Object { $_.Name -match 'powershell|pwsh' -and $_.CommandLine -match "WindowTitle='FornexIA - " }       | ForEach-Object { [pscustomobject]@{ Pid = $_.ProcessId; Quem = 'janela do ligar-tudo' } }

if (@($alvos).Count -eq 0) { Write-Host 'Nada do projeto estava rodando.' -ForegroundColor Gray }
foreach ($a in $alvos) {
    if ($Simular) { Write-Host ("  [simulação] encerraria PID {0,-6} {1}" -f $a.Pid, $a.Quem) }
    else {
        Stop-Process -Id $a.Pid -Force -ErrorAction SilentlyContinue
        Write-Host ("  [OK] encerrado PID {0,-6} {1}" -f $a.Pid, $a.Quem) -ForegroundColor Green
    }
}

if (-not $Simular) {
    # O gateway morto à força não escreve "parado". Sem isto, o status.json ficaria dizendo "conectado" e enganaria o próximo ligar-tudo.
    $f = Join-Path $estado 'status.json'
    if ((Test-Path $f) -and ($alvos | Where-Object { $_.Quem -eq 'gateway do WhatsApp' })) {
        try {
            $s = Get-Content $f -Raw | ConvertFrom-Json
            $s.conectado = $false
            $s | Add-Member -NotePropertyName parado -NotePropertyValue $true -Force
            $s | ConvertTo-Json | Set-Content $f -Encoding utf8
        } catch { }
    }
    if ($ComBancos) {
        Write-Host 'Desligando os bancos (os dados ficam guardados nos volumes)...'
        Push-Location $raiz
        docker compose -f site/dev/docker-compose.yml stop 2>&1 | Out-Null
        docker compose --env-file .env -f infra/docker-compose.yml stop neo4j 2>&1 | Out-Null
        Pop-Location
        Write-Host '  [OK] bancos parados' -ForegroundColor Green
    }
    Write-Host 'Pronto. Para ligar de novo: dois cliques em ligar-tudo.bat (no PowerShell: .\ligar-tudo.bat)' -ForegroundColor Cyan
}
