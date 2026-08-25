[CmdletBinding()]
param(
    [string]$App = 'choque-bgr-api',
    [string]$StageRoot = (Join-Path $env:TEMP 'choque-discloud-staging')
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$stage = Join-Path $StageRoot ([guid]::NewGuid().ToString('N'))
$sourceDirectories = @('choque', 'cogs', 'command_center', 'scripts')
$rootFiles = @(
    '.discloudignore', 'discloud.config', '.env.example', '.gitignore',
    'config.example.json', 'main.py', 'pyproject.toml', 'requirements.txt',
    'README.md', 'SECURITY.md', 'uv.lock'
)

New-Item -ItemType Directory -Path $stage -Force | Out-Null
foreach ($directory in $sourceDirectories) {
    $source = Join-Path $projectRoot $directory
    if (-not (Test-Path -LiteralPath $source)) {
        throw "Diretório obrigatório ausente: $source"
    }
    Copy-Item -LiteralPath $source -Destination $stage -Recurse -Force
}
foreach ($file in $rootFiles) {
    $source = Join-Path $projectRoot $file
    if (Test-Path -LiteralPath $source) {
        Copy-Item -LiteralPath $source -Destination $stage -Force
    }
}

$required = @(
    (Join-Path $stage 'command_center\app.py'),
    (Join-Path $stage 'choque\financial_aid.py'),
    (Join-Path $stage 'cogs\financial_aid_commands.py'),
    (Join-Path $stage 'scripts\bootstrap_financial_pix.py'),
    (Join-Path $stage 'scripts\run_combined.py'),
    (Join-Path $stage 'main.py'),
    (Join-Path $stage 'discloud.config')
)
foreach ($path in $required) {
    if (-not (Test-Path -LiteralPath $path)) {
        throw "Artefato de deploy incompleto: $path"
    }
}
if (Get-ChildItem -LiteralPath $stage -Recurse -File |
    Where-Object { $_.FullName -match '\\(artifacts|data)\\|\.(db|sqlite|sqlite3)(-|$)' }) {
    throw 'O stage contém artefato proibido (backup, dados ou banco).'
}

Push-Location $stage
try {
    discloud app commit $App
} finally {
    Pop-Location
}

Write-Output "DISCLOUD_STAGE_DEPLOYED app=$App stage=$stage"
