[CmdletBinding()]
param(
    [string]$App = 'choque-bgr-api',
    [Parameter(Mandatory = $true)]
    [string]$BaseStageRoot,
    [string]$StageRoot = (Join-Path $env:TEMP 'choque-rank-announcement-staging')
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$base = (Resolve-Path -LiteralPath $BaseStageRoot).Path
$stage = Join-Path $StageRoot ([guid]::NewGuid().ToString('N'))
$overlay = @(
    'choque\rank_sync.py',
    'choque\settings.py',
    'cogs\rank_sync_system.py',
    'cogs\career_commands.py',
    'scripts\configure_elite_unit.py'
)

foreach ($required in @('choque', 'cogs', 'command_center', 'scripts', 'main.py', 'discloud.config')) {
    if (-not (Test-Path -LiteralPath (Join-Path $base $required))) {
        throw "Stage-base incompleto: $required"
    }
}

New-Item -ItemType Directory -Path $StageRoot -Force | Out-Null
Copy-Item -LiteralPath $base -Destination $stage -Recurse -Force
foreach ($relative in $overlay) {
    $source = Join-Path $projectRoot $relative
    $destination = Join-Path $stage $relative
    if (-not (Test-Path -LiteralPath $source)) {
        throw "Overlay obrigatório ausente: $source"
    }
    New-Item -ItemType Directory -Path (Split-Path -Parent $destination) -Force | Out-Null
    Copy-Item -LiteralPath $source -Destination $destination -Force
}

$markers = @(
    @('cogs\financial_aid_commands.py', 'delete_original_response'),
    @('choque\database.py', 'request_card_rendered_version'),
    @('cogs\shift_commands.py', 'Meu Ponto'),
    @('choque\rank_sync.py', 'rank-role-notification-')
)
foreach ($marker in $markers) {
    if (-not (Select-String -LiteralPath (Join-Path $stage $marker[0]) -SimpleMatch $marker[1])) {
        throw "Stage perdeu uma entrega anterior ou o novo overlay: $($marker[0])"
    }
}

$configLines = Get-Content -LiteralPath (Join-Path $stage 'discloud.config')
foreach ($line in @('TYPE=site', "ID=$App", 'MAIN=scripts/run_combined.py', 'START=python scripts/run_combined.py')) {
    if ($configLines -notcontains $line) {
        throw "Configuração combinada ausente: $line"
    }
}

$prohibited = Get-ChildItem -LiteralPath $stage -Recurse -File |
    Where-Object {
        $_.Name -in @('.env', '.env.combined') -or
        $_.Extension -in @('.db', '.sqlite', '.sqlite3', '.pyc') -or
        $_.FullName -match '\\(artifacts|data|__pycache__)\\'
    }
if ($prohibited) {
    throw "Stage contém artefato proibido: $($prohibited[0].FullName)"
}

$env:PYTHONDONTWRITEBYTECODE = '1'
Push-Location $stage
try {
    python -c "from choque.rank_sync import RankSyncService; from cogs.rank_sync_system import RankSyncSystem; from cogs.career_commands import CareerCommands; print('RANK_ANNOUNCEMENT_STAGE_OK')"
    if ($LASTEXITCODE -ne 0) {
        throw 'Falha de importação no stage de movimentações.'
    }
    discloud app commit $App
} finally {
    Pop-Location
}

Write-Output "RANK_ANNOUNCEMENT_DEPLOY_SENT app=$App stage=$stage files=$($overlay.Count)"
