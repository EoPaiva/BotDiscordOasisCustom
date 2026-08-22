$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$pidPath = Join-Path $projectRoot "data\bot.pid"
$mainPath = Join-Path $projectRoot "main.py"

function Get-ProjectBotProcesses {
    $escapedMainPath = [Regex]::Escape($mainPath)
    @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
        $_.CommandLine -and $_.CommandLine -match ('(?i)["'']?' + $escapedMainPath + '["'']?(?:\s|$)')
    })
}

$running = Get-ProjectBotProcesses
if ($running.Count -gt 0) {
    $runningIds = $running.ProcessId | Sort-Object -Unique
    Set-Content -LiteralPath $pidPath -Value $runningIds -Encoding ascii
    Write-Output "BOT_ONLINE pids=$(($runningIds) -join ',')"
    exit 0
}

Remove-Item -LiteralPath $pidPath -Force -ErrorAction SilentlyContinue
Write-Output "BOT_OFFLINE"
exit 1
