# Verificaciones locales: lint, formato, tipos, pruebas y coherencia de la versión de ruff.
# Uso: powershell -ExecutionPolicy Bypass -File scripts/check.ps1
# Requiere el entorno creado con `uv sync` (carpeta .venv).
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
$bin = Join-Path (Get-Location) ".venv\Scripts"
if (-not (Test-Path (Join-Path $bin "ruff.exe"))) {
    throw "No existe .venv. Ejecute 'uv sync' primero."
}

function Invoke-Step([string]$Name, [scriptblock]$Command) {
    Write-Output "==> $Name"
    & $Command
    if ($LASTEXITCODE -ne 0) { throw "Falló: $Name" }
}

Invoke-Step "ruff check" { & "$bin\ruff.exe" check . }
Invoke-Step "ruff format --check" { & "$bin\ruff.exe" format --check . }
Invoke-Step "pyright" { & "$bin\pyright.exe" }
Invoke-Step "pytest" { & "$bin\pytest.exe" -q }

Write-Output "==> versión de ruff: uv.lock frente a pre-commit"
$locked = [regex]::Match((Get-Content uv.lock -Raw), '(?m)^name = "ruff"\r?\nversion = "([^"]+)"').Groups[1].Value
$hook = [regex]::Match((Get-Content .pre-commit-config.yaml -Raw), 'rev: v(\S+)').Groups[1].Value
if (-not $locked -or $locked -ne $hook) {
    throw "ruff desalineado: uv.lock=$locked, .pre-commit-config.yaml=$hook"
}
Write-Output "OK ruff $locked"
Write-Output "Todas las verificaciones pasaron."
