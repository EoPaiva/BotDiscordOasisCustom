[CmdletBinding(SupportsShouldProcess)]
param(
    [string]$App = 'choque-bgr-api',
    [switch]$DeployWeb,
    [int]$OnlineTimeoutSeconds = 180,
    [int]$StabilitySeconds = 45
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$webRoot = Join-Path $projectRoot 'web'
$backendDeploy = Join-Path $PSScriptRoot 'deploy_discloud_staged.ps1'

function Invoke-Checked {
    param(
        [Parameter(Mandatory)] [string]$Program,
        [Parameter(Mandatory)] [string[]]$Arguments,
        [Parameter(Mandatory)] [string]$WorkingDirectory
    )

    Push-Location $WorkingDirectory
    try {
        & $Program @Arguments
        if ($LASTEXITCODE -ne 0) {
            throw "Falha em $Program $($Arguments -join ' ') (exit $LASTEXITCODE)."
        }
    } finally {
        Pop-Location
    }
}

Write-Output 'RECRUITMENT_ROLLOUT preflight=started'
Invoke-Checked -Program 'python' -Arguments @(
    '-m', 'pytest', 'tests/test_recruitment.py', '-q'
) -WorkingDirectory $projectRoot
Invoke-Checked -Program 'python' -Arguments @(
    '-m', 'ruff', 'check', 'choque/recruitment.py', 'tests/test_recruitment.py'
) -WorkingDirectory $projectRoot
Invoke-Checked -Program 'npm' -Arguments @('test', '--', '--run') -WorkingDirectory $webRoot
Invoke-Checked -Program 'npm' -Arguments @('run', 'lint') -WorkingDirectory $webRoot
Invoke-Checked -Program 'npm' -Arguments @('run', 'build') -WorkingDirectory $webRoot
Write-Output 'RECRUITMENT_ROLLOUT preflight=passed'

if (-not $PSCmdlet.ShouldProcess($App, 'backup and deploy backend before web')) {
    Write-Output 'RECRUITMENT_ROLLOUT deployment=whatif'
    return
}

$backupRoot = Join-Path $env:TEMP (
    'choque-recruitment-backup-' + [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ')
)
New-Item -ItemType Directory -Path $backupRoot -Force | Out-Null
Invoke-Checked -Program 'discloud' -Arguments @(
    'app', 'backup', $App, $backupRoot, '-s'
) -WorkingDirectory $projectRoot

& $backendDeploy -App $App
if ($LASTEXITCODE -ne 0) {
    throw "Deploy do backend falhou (exit $LASTEXITCODE). Backup: $backupRoot"
}

$deadline = [DateTime]::UtcNow.AddSeconds($OnlineTimeoutSeconds)
$online = $false
$onlineSince = $null
do {
    $status = (& discloud app status $App 2>&1 | Out-String)
    if ($LASTEXITCODE -eq 0 -and $status -match "(?m)^$([regex]::Escape($App))\s+Online\s") {
        if ($null -eq $onlineSince) {
            $onlineSince = [DateTime]::UtcNow
        }
        if (([DateTime]::UtcNow - $onlineSince).TotalSeconds -ge $StabilitySeconds) {
            $online = $true
            break
        }
    } else {
        $onlineSince = $null
    }
    Start-Sleep -Seconds 5
} while ([DateTime]::UtcNow -lt $deadline)

if (-not $online) {
    throw "Backend não permaneceu Online por $StabilitySeconds segundos dentro do prazo. Backup: $backupRoot"
}
Write-Output "RECRUITMENT_ROLLOUT backend=stable stability_seconds=$StabilitySeconds backup=$backupRoot"

if (-not $DeployWeb) {
    Write-Output 'RECRUITMENT_ROLLOUT web=skipped use=-DeployWeb'
    return
}

if (-not (Get-Command vercel -ErrorAction SilentlyContinue)) {
    throw 'Vercel CLI ausente. Instale com: npm i -g vercel'
}
Invoke-Checked -Program 'vercel' -Arguments @('deploy', '--prod', '--yes') -WorkingDirectory $webRoot
Write-Output 'RECRUITMENT_ROLLOUT web=deployed'
