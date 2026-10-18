# Runs the full Phase quality gate. Usage:
#   powershell -ExecutionPolicy Bypass -File scripts/check.ps1
$ErrorActionPreference = "Stop"

$py = ".\.venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    $py = "python"
}

Write-Host "==> Django system check" -ForegroundColor Cyan
& $py manage.py check

Write-Host "==> Missing migrations check" -ForegroundColor Cyan
& $py manage.py makemigrations --check --dry-run

Write-Host "==> Ruff lint" -ForegroundColor Cyan
& $py -m ruff check .

Write-Host "==> Ruff format check" -ForegroundColor Cyan
& $py -m ruff format --check .

Write-Host "==> pytest" -ForegroundColor Cyan
& $py -m pytest

Write-Host "All checks passed." -ForegroundColor Green
