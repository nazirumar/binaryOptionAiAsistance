# scripts/run_all.ps1
# ---------------------------------------------------------------------------
# Single-file launcher: starts the whole local stack at once.
#
#   powershell -ExecutionPolicy Bypass -File scripts/run_all.ps1
#
# What it starts (mirrors compose.yaml / compose.prod.yaml):
#   web              uvicorn ASGI on http://127.0.0.1:8000, or Django
#                    runserver when uvicorn is not installed (dev venv)
#   worker-market    Celery, queues  market,default   (concurrency 2)
#   worker-vision    Celery, queue   vision           (concurrency 1)
#   worker-backtest  Celery, queue   backtest         (concurrency 1)
#   worker-assistant Celery, queue   assistant        (concurrency 2)
#   beat             Celery beat     (retention purges + health probe)
#
# Each process writes a live log under .run-logs/ (<name>.log) and the parent
# window shows a merged tail. Press Ctrl+C once to stop everything.
#
# Windows note: Celery runs with --pool solo by default (prefork is unreliable
# on Windows). Pass -SoloPool to force it explicitly.
#
# Requirements:
#   * .venv present (falls back to "python" on PATH)
#   * REDIS_URL set in .env or the environment, and the broker reachable.
#     Celery workers + beat need a real broker; without it tasks run eagerly
#     in-process and there is nothing to "start at once". The script refuses
#     to start rather than pretend.
#
# Nothing here reads, prints or writes secrets. The MT5 Windows worker is a
# SEPARATE host (python manage.py mt5_worker) and is intentionally not started
# here. No production deployment: this is a local/dev helper only.
# ---------------------------------------------------------------------------
[CmdletBinding()]
param(
    # Django settings module to run under.
    [string]$Settings = "",

    # Web bind host/port.
    [string]$Host_ = "127.0.0.1",
    [int]$Port = 8000,

    # Skip the web server (workers + beat only).
    [switch]$NoWeb,

    # Force Celery "solo" pool (Windows-safe; required if prefork misbehaves).
    [switch]$SoloPool
)

$ErrorActionPreference = "Stop"

# --- Resolve project root (this file lives in <root>/scripts) ---------------
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Split-Path -Parent $ScriptDir
Set-Location $Root

# --- Locate the interpreter ------------------------------------------------
$py = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    $py = (Get-Command python -ErrorAction SilentlyContinue).Source
    if (-not $py) {
        Write-Host "ERROR: no Python found (.venv\Scripts\python.exe or python on PATH)." -ForegroundColor Red
        exit 1
    }
    Write-Host "WARN: .venv not found; using $py" -ForegroundColor Yellow
}

# Celery is always invoked as a module through the same interpreter ($py
# "-m celery ..."). Using the console-script shim would require pointing
# Start-Process at celery.exe; the module form is deterministic and works the
# same whether or not the shim exists.

# --- Settings module --------------------------------------------------------
if (-not $Settings) {
    if ($env:DJANGO_SETTINGS_MODULE) {
        $Settings = $env:DJANGO_SETTINGS_MODULE
    }
    else {
        $Settings = "config.settings.dev"
    }
}
$env:DJANGO_SETTINGS_MODULE = $Settings

Write-Host "==> Project root : $Root" -ForegroundColor Cyan
Write-Host "==> Python       : $py" -ForegroundColor Cyan
Write-Host "==> Settings     : $Settings" -ForegroundColor Cyan

# --- Resolve REDIS_URL (.env then real env; env wins, like django-environ) ---
function Get-DotEnvValue([string]$key) {
    $envFile = Join-Path $Root ".env"
    if (-not (Test-Path $envFile)) { return "" }
    foreach ($line in Get-Content $envFile) {
        $trimmed = $line.Trim()
        if ($trimmed -eq "" -or $trimmed.StartsWith("#")) { continue }
        $idx = $trimmed.IndexOf("=")
        if ($idx -lt 1) { continue }
        $name = $trimmed.Substring(0, $idx).Trim()
        if ($name -ne $key) { continue }
        $value = $trimmed.Substring($idx + 1).Trim()
        # Strip surrounding quotes if present.
        $value = $value.Trim('"').Trim("'")
        return $value
    }
    return ""
}

$redisUrl = $env:REDIS_URL
if (-not $redisUrl) { $redisUrl = Get-DotEnvValue "REDIS_URL" }

if (-not $redisUrl) {
    Write-Host ""
    Write-Host "ERROR: REDIS_URL is not set (checked the environment and .env)." -ForegroundColor Red
    Write-Host "       Celery workers + beat need a real broker; without it tasks run" -ForegroundColor Red
    Write-Host "       eagerly in-process and there is nothing to 'start at once'." -ForegroundColor Red
    Write-Host ""
    Write-Host "       Fix: set REDIS_URL in .env, e.g." -ForegroundColor Yellow
    $pw = Get-DotEnvValue "REDIS_PASSWORD"
    $rp = Get-DotEnvValue "REDIS_PORT"
    if (-not $rp) { $rp = "6379" }
    if ($pw) {
        Write-Host ("         REDIS_URL=redis://:{0}@127.0.0.1:{1}/0" -f $pw, $rp) -ForegroundColor Yellow
        Write-Host "       (uses the REDIS_PASSWORD already in your .env)" -ForegroundColor Yellow
    }
    else {
        Write-Host "         REDIS_URL=redis://127.0.0.1:6379/0" -ForegroundColor Yellow
    }
    Write-Host "       and make sure Redis is running, e.g." -ForegroundColor Yellow
    Write-Host ("         docker run --rm -p {0}:6379 redis:7-alpine" -f $rp) -ForegroundColor Yellow
    exit 1
}
$env:REDIS_URL = $redisUrl
# A visible broker means non-eager is what we want; make sure we do not inherit
# an eager flag from the shell.
$env:CELERY_TASK_ALWAYS_EAGER = "False"

# Child stdout is redirected to files, so Python would block-buffer it and the
# live tail would look empty. Force line/unbuffered output for every child.
$env:PYTHONUNBUFFERED = "1"

# --- Broker reachability probe ---------------------------------------------
# A set-but-dead REDIS_URL is worse than an unset one: the workers would launch
# and then sit silently retrying forever. Use Celery's own Redis client to PING,
# so host/port/db/password parsing matches what the workers will use.
$probe = & $py -c @"
import sys
try:
    from celery import Celery
    app = Celery(broker=sys.argv[1])
    with app.connection_for_read() as conn:
        conn.ensure_connection(max_retries=1, timeout=3)
    print('OK')
except Exception as exc:
    print('FAIL: %s' % exc)
"@ $redisUrl 2>&1

if ($LASTEXITCODE -ne 0 -or ($probe -join "`n") -notmatch "^OK") {
    Write-Host ""
    Write-Host "ERROR: REDIS_URL is set but the broker is not reachable:" -ForegroundColor Red
    Write-Host "       $redisUrl" -ForegroundColor DarkGray
    Write-Host "       $($probe -join ' ')" -ForegroundColor DarkGray
    Write-Host ""
    Write-Host "       Start Redis first, e.g." -ForegroundColor Yellow
    Write-Host "         docker run --rm -p 6379:6379 redis:7-alpine" -ForegroundColor Yellow
    Write-Host "       (and match the password/port in REDIS_URL)." -ForegroundColor Yellow
    exit 1
}
Write-Host "==> Broker       : reachable" -ForegroundColor Cyan

# --- Web server selection ---------------------------------------------------
# uvicorn is a production dependency; the dev venv usually lacks it (and
# gunicorn is Linux-only). Fall back to Django's runserver, which serves ASGI/
# Channels in development. Inform the user which one is used.
$webMode = ""
$uvicornOk = $false
try {
    & $py -c "import uvicorn" 2>$null
    $uvicornOk = ($LASTEXITCODE -eq 0)
}
catch { $uvicornOk = $false }

if ($uvicornOk) { $webMode = "uvicorn" }
else { $webMode = "runserver" }

# --- Prepare log directory --------------------------------------------------
$logDir = Join-Path $Root ".run-logs"
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }
# Fresh logs each run so a stale file is never mistaken for a live process.
Get-ChildItem $logDir -Filter *.log -ErrorAction SilentlyContinue | Remove-Item -Force

# --- Process registry -------------------------------------------------------
$processes = @()

function Start-StackProcess {
    param(
        [string]$Name,
        [string]$File,
        [string[]]$Arguments,
        # Redirect child stdout somewhere other than .log (used for Celery,
        # which writes its own --logfile; its console streams only carry stray
        # prints). Start-Process requires stdout and stderr to differ.
        [switch]$ConsoleToErr
    )
    $logPath = Join-Path $logDir "$Name.log"
    $errPath = Join-Path $logDir "$Name.err.log"
    $consolePath = Join-Path $logDir "$Name.console.log"
    $stdoutTarget = if ($ConsoleToErr) { $consolePath } else { $logPath }
    Write-Host ("  - {0,-16} -> {1}" -f $Name, (Split-Path -Leaf $logPath)) -ForegroundColor DarkGray
    try {
        $proc = Start-Process -FilePath $File -ArgumentList $Arguments `
            -WorkingDirectory $Root -NoNewWindow -PassThru `
            -RedirectStandardOutput $stdoutTarget `
            -RedirectStandardError $errPath
    }
    catch {
        Write-Host ("    ! failed to start {0}: {1}" -f $Name, $_.Exception.Message) -ForegroundColor Red
        return
    }
    $script:processes += [pscustomobject]@{ Name = $Name; Proc = $proc; Log = $logPath }
}

# Celery can write its own logfile (its logging layer flushes reliably, which
# Windows stdout redirection does not always do). We point --logfile at the
# same .run-logs/<name>.log so the live tail and the file agree.
function Start-CeleryProcess {
    param(
        [string]$Name,
        [string[]]$Rest
    )
    $logPath = Join-Path $logDir "$Name.log"
    $args = (Get-CeleryArgs $Rest) + @("--logfile", $logPath, "-l", "info")
    Start-StackProcess -Name $Name -File $py -Arguments $args -ConsoleToErr
}

function Get-CeleryArgs {
    param([string[]]$Rest)
    # Always run Celery through the selected interpreter as a module.
    return , (@("-m", "celery") + $Rest)
}

# Windows + Celery prefork can misbehave; default to a worker-friendly pool.
$poolArgs = @()
if ($SoloPool -or ($IsWindows -or $env:OS -eq "Windows_NT")) {
    # "solo" is the safest cross-platform pool for local single-machine runs.
    $poolArgs = @("--pool", "solo")
}

Write-Host "`n==> Starting processes" -ForegroundColor Cyan

# --- Web --------------------------------------------------------------------
if (-not $NoWeb) {
    if ($webMode -eq "uvicorn") {
        Start-StackProcess -Name "web" -File $py -Arguments @(
            "-m", "uvicorn", "config.asgi:application",
            "--host", $Host_, "--port", "$Port"
        )
    }
    else {
        Start-StackProcess -Name "web" -File $py -Arguments @(
            "manage.py", "runserver", "$Host_`:$Port"
        )
    }
}

# --- Celery workers (one per queue, mirroring compose.yaml) -----------------
Start-CeleryProcess -Name "worker-market" `
    -Rest (@("-A", "config", "worker", "-Q", "market,default", "-c", "2", "--max-tasks-per-child", "50") + $poolArgs)

Start-CeleryProcess -Name "worker-vision" `
    -Rest (@("-A", "config", "worker", "-Q", "vision", "-c", "1", "--max-tasks-per-child", "20") + $poolArgs)

Start-CeleryProcess -Name "worker-backtest" `
    -Rest (@("-A", "config", "worker", "-Q", "backtest", "-c", "1", "--max-tasks-per-child", "5") + $poolArgs)

Start-CeleryProcess -Name "worker-assistant" `
    -Rest (@("-A", "config", "worker", "-Q", "assistant", "-c", "2", "--max-tasks-per-child", "50") + $poolArgs)

# --- Beat (scheduler) -------------------------------------------------------
$beatSchedule = Join-Path $logDir "celerybeat-schedule"
Start-CeleryProcess -Name "beat" `
    -Rest @("-A", "config", "beat", "--schedule", $beatSchedule)

# --- Report -----------------------------------------------------------------
Write-Host "`n==> Stack is up. $($processes.Count) process(es)." -ForegroundColor Green
if (-not $NoWeb) {
    $scheme = "http"
    Write-Host ("    Web: {0}://{1}:{2}/  ({3})" -f $scheme, $Host_, $Port, $webMode) -ForegroundColor Green
}
Write-Host "    Logs: $logDir" -ForegroundColor Green
Write-Host "    Press Ctrl+C to stop everything.`n" -ForegroundColor Green

# --- Watch: restart nothing, but surface an early death quickly -------------
function Stop-All {
    Write-Host "`n==> Shutting down..." -ForegroundColor Yellow
    foreach ($entry in $script:processes) {
        try {
            if ($entry.Proc -and -not $entry.Proc.HasExited) {
                # Kill the process tree (Celery spawns children on prefork).
                & taskkill /PID $entry.Proc.Id /T /F 2>$null | Out-Null
            }
        }
        catch { }
    }
    Write-Host "==> Stopped." -ForegroundColor Yellow
}

# Names already reported as dead, so a crashed child is announced once and its
# warning is not lost to the periodic Clear-Host.
$reportedDead = @{}

try {
    while ($true) {
        foreach ($entry in $script:processes) {
            if ($entry.Proc.HasExited -and -not $reportedDead.ContainsKey($entry.Name)) {
                $reportedDead[$entry.Name] = $true
                Write-Host ("`nWARN: {0} exited early (code {1}). See {2}" -f `
                        $entry.Name, $entry.Proc.ExitCode, $entry.Log) -ForegroundColor Red
                Start-Sleep -Seconds 3
            }
        }

        # Merge the tail of every log into this window for a live view.
        Clear-Host
        Write-Host "==> Local stack (Ctrl+C to stop)" -ForegroundColor Cyan
        if ($reportedDead.Count -gt 0) {
            Write-Host ("    DEAD: {0}" -f (($reportedDead.Keys | Sort-Object) -join ", ")) -ForegroundColor Red
        }
        foreach ($entry in $script:processes) {
            $state = if ($entry.Proc.HasExited) { "STOPPED" } else { "running" }
            Write-Host ("`n--- {0} [{1}] ---" -f $entry.Name, $state) -ForegroundColor DarkGray
            if (Test-Path $entry.Log) {
                Get-Content $entry.Log -Tail 6 -ErrorAction SilentlyContinue |
                    ForEach-Object { Write-Host "  $_" }
            }
        }
        Start-Sleep -Seconds 2
    }
}
finally {
    Stop-All
}
