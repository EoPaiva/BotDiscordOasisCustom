[CmdletBinding()]
param(
    [string]$App = 'choque-bgr-api',
    [Parameter(Mandatory = $true)]
    [string]$RemoteSnapshotRoot,
    [string]$StageRoot = (Join-Path $env:TEMP 'choque-financial-aid-staging'),
    [switch]$SkipCommit
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$remoteRoot = (Resolve-Path -LiteralPath $RemoteSnapshotRoot).Path
$stage = Join-Path $StageRoot ([guid]::NewGuid().ToString('N'))
$sourceDirectories = @('choque', 'cogs', 'command_center', 'scripts')
$rootFiles = @(
    '.discloudignore', 'discloud.config', '.env.example', '.gitignore',
    'config.example.json', 'main.py', 'pyproject.toml', 'requirements.txt',
    'README.md', 'SECURITY.md', 'uv.lock'
)
$financialOverlay = @(
    'choque\\database.py',
    'choque\\financial_aid.py',
    'cogs\\financial_aid_commands.py',
    'scripts\\provision_financial_aid.py',
    'scripts\\publish_financial_update.py',
    'scripts\\publish_system_updates.py'
)

foreach ($directory in $sourceDirectories) {
    if (-not (Test-Path -LiteralPath (Join-Path $remoteRoot $directory))) {
        throw "Snapshot remoto incompleto: $directory"
    }
}

New-Item -ItemType Directory -Path $stage -Force | Out-Null
foreach ($directory in $sourceDirectories) {
    $source = Join-Path $remoteRoot $directory
    Get-ChildItem -LiteralPath $source -File -Recurse |
        Where-Object {
            $_.Extension -ne '.pyc' -and $_.FullName -notmatch '\\__pycache__\\'
        } |
        ForEach-Object {
            $relative = $_.FullName.Substring($source.Length).TrimStart('\\')
            $destination = Join-Path $stage (Join-Path $directory $relative)
            New-Item -ItemType Directory -Path (Split-Path -Parent $destination) -Force | Out-Null
            Copy-Item -LiteralPath $_.FullName -Destination $destination -Force
        }
}
foreach ($file in $rootFiles) {
    $source = Join-Path $remoteRoot $file
    if (Test-Path -LiteralPath $source) {
        Copy-Item -LiteralPath $source -Destination (Join-Path $stage $file) -Force
    }
}
foreach ($relative in $financialOverlay) {
    $source = Join-Path $projectRoot $relative
    if (-not (Test-Path -LiteralPath $source)) {
        throw "Arquivo financeiro obrigatório ausente: $source"
    }
    $destination = Join-Path $stage $relative
    New-Item -ItemType Directory -Path (Split-Path -Parent $destination) -Force | Out-Null
    Copy-Item -LiteralPath $source -Destination $destination -Force
}

$required = @(
    (Join-Path $stage 'command_center\\app.py'),
    (Join-Path $stage 'choque\\financial_aid.py'),
    (Join-Path $stage 'cogs\\financial_aid_commands.py'),
    (Join-Path $stage 'scripts\\bootstrap_financial_pix.py'),
    (Join-Path $stage 'scripts\\provision_financial_aid.py'),
    (Join-Path $stage 'scripts\\publish_financial_update.py'),
    (Join-Path $stage 'scripts\\run_combined.py'),
    (Join-Path $stage 'main.py'),
    (Join-Path $stage 'discloud.config')
)
foreach ($path in $required) {
    if (-not (Test-Path -LiteralPath $path)) {
        throw "Artefato de deploy incompleto: $path"
    }
}
$configLines = Get-Content -LiteralPath (Join-Path $stage 'discloud.config')
$requiredConfig = @(
    'TYPE=site',
    "ID=$App",
    'MAIN=scripts/run_combined.py',
    'START=python scripts/run_combined.py'
)
foreach ($line in $requiredConfig) {
    if ($configLines -notcontains $line) {
        throw "Configuração Discloud não corresponde ao runtime combinado esperado: $line"
    }
}
& python -m compileall -q (Join-Path $stage 'choque') (Join-Path $stage 'cogs') (Join-Path $stage 'command_center') (Join-Path $stage 'scripts')
if ($LASTEXITCODE -ne 0) {
    throw 'Falha de compilação no artefato financeiro preparado.'
}
Push-Location $stage
try {
    & python -c "from choque.financial_aid import FinancialAidService; from cogs.financial_aid_commands import FinancialAidCommands; from scripts.provision_financial_aid import provision; from scripts.publish_financial_update import publish; print('FINANCIAL_STAGE_IMPORT_OK')"
    if ($LASTEXITCODE -ne 0) {
        throw 'Falha de importação no artefato financeiro preparado.'
    }
} finally {
    Pop-Location
}

# Compile/import checks create local bytecode.  Remove only those individual
# files from this freshly-created stage, then remove the now-empty cache dirs.
Get-ChildItem -LiteralPath $stage -Recurse -File -Filter '*.pyc' |
    ForEach-Object { Remove-Item -LiteralPath $_.FullName -Force }
Get-ChildItem -LiteralPath $stage -Recurse -Directory |
    Where-Object { $_.Name -eq '__pycache__' } |
    Sort-Object FullName -Descending |
    ForEach-Object { Remove-Item -LiteralPath $_.FullName -Force }

$prohibited = Get-ChildItem -LiteralPath $stage -Recurse -File |
    Where-Object {
        $_.Name -in @('.env', '.env.combined') -or
        $_.Extension -in @('.db', '.sqlite', '.sqlite3', '.pyc') -or
        $_.FullName -match '\\(artifacts|data|__pycache__)\\'
    }
if ($prohibited) {
    throw "O stage contém artefato proibido: $($prohibited[0].FullName)"
}

$manifest = $financialOverlay |
    ForEach-Object { Get-FileHash -LiteralPath (Join-Path $stage $_) -Algorithm SHA256 } |
    ForEach-Object { "$($_.Path.Substring($stage.Length).TrimStart('\\')):$($_.Hash)" }
$manifest | Set-Content -LiteralPath (Join-Path $stage 'FINANCIAL_OVERLAY_MANIFEST.txt') -Encoding utf8

if ($SkipCommit) {
    Write-Output "DISCLOUD_FINANCIAL_STAGE_READY app=$App stage=$stage files=$($financialOverlay.Count)"
    return
}

Push-Location $stage
try {
    discloud app commit $App
} finally {
    Pop-Location
}

Write-Output "DISCLOUD_FINANCIAL_OVERLAY_DEPLOYED app=$App stage=$stage files=$($financialOverlay.Count)"
