$ErrorActionPreference = "Stop"

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$pidPath = Join-Path $projectRoot "data\bot.pid"
$logsPath = Join-Path $projectRoot "logs"
$mainPath = Join-Path $projectRoot "main.py"

function Get-ProjectBotProcesses {
    $escapedMainPath = [Regex]::Escape($mainPath)
    @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
        $_.CommandLine -and $_.CommandLine -match ('(?i)["'']?' + $escapedMainPath + '["'']?(?:\s|$)')
    })
}

$existing = Get-ProjectBotProcesses
if ($existing.Count -gt 0) {
    $existingIds = ($existing.ProcessId | Sort-Object -Unique) -join ","
    Set-Content -LiteralPath $pidPath -Value ($existing.ProcessId | Sort-Object -Unique) -Encoding ascii
    Write-Output "BOT_ALREADY_RUNNING pids=$existingIds"
    exit 0
}
Remove-Item -LiteralPath $pidPath -Force -ErrorAction SilentlyContinue

New-Item -ItemType Directory -Force -Path (Split-Path $pidPath) | Out-Null
New-Item -ItemType Directory -Force -Path $logsPath | Out-Null

$venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
$python = if (Test-Path -LiteralPath $venvPython) {
    $venvPython
} else {
    (Get-Command python).Source
}
$stdout = Join-Path $logsPath "bot.out.log"
$stderr = Join-Path $logsPath "bot.err.log"
$process = Start-Process `
    -FilePath $python `
    -ArgumentList ('"{0}"' -f $mainPath) `
    -WorkingDirectory $projectRoot `
    -WindowStyle Hidden `
    -RedirectStandardOutput $stdout `
    -RedirectStandardError $stderr `
    -PassThru

Start-Sleep -Seconds 3
$running = Get-ProjectBotProcesses
if ($running.Count -eq 0) {
    Remove-Item -LiteralPath $pidPath -Force -ErrorAction SilentlyContinue
    Write-Error "O bot encerrou durante o startup. Consulte logs\bot.err.log."
}

$runningIds = $running.ProcessId | Sort-Object -Unique
Set-Content -LiteralPath $pidPath -Value $runningIds -Encoding ascii
Write-Output "BOT_STARTED pids=$(($runningIds) -join ',') launcher_pid=$($process.Id)"
