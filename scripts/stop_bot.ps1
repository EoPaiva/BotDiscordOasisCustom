$ErrorActionPreference = "Stop"

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$pidPath = Join-Path $projectRoot "data\bot.pid"
$mainPath = Join-Path $projectRoot "main.py"

function Get-ProjectBotProcesses {
    $escapedMainPath = [Regex]::Escape($mainPath)
    @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
        $_.CommandLine -and $_.CommandLine -match ('(?i)["'']?' + $escapedMainPath + '["'']?(?:\s|$)')
    })
}

$botProcesses = Get-ProjectBotProcesses
if ($botProcesses.Count -eq 0) {
    Remove-Item -LiteralPath $pidPath -Force -ErrorAction SilentlyContinue
    Write-Output "BOT_NOT_RUNNING"
    exit 0
}

$botIds = $botProcesses.ProcessId | Sort-Object -Unique
foreach ($botPid in ($botIds | Sort-Object -Descending)) {
    Stop-Process -Id $botPid -ErrorAction SilentlyContinue
}
foreach ($botPid in $botIds) {
    Wait-Process -Id $botPid -Timeout 10 -ErrorAction SilentlyContinue
}

$remaining = Get-ProjectBotProcesses
if ($remaining.Count -gt 0) {
    throw "Não foi possível encerrar todos os processos do bot: $(($remaining.ProcessId) -join ',')."
}

Remove-Item -LiteralPath $pidPath -Force -ErrorAction SilentlyContinue
Write-Output "BOT_STOPPED pids=$(($botIds) -join ',')"
