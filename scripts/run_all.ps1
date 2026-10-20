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

    # Also start the MT5 Windows data worker (separate host by default; opt-in
    # here so a machine without a live terminal is never left with a dead
    # worker). A bounded preflight proves the terminal is reachable first.
    [switch]$WithMT5,

    # Seconds to wait for the MT5 preflight connection before giving up.
    [int]$MT5ProbeTimeoutSeconds = 45,

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

# --- Pre-flight: clear a stale listener on the web port ---------------------
# A previously interrupted run (Ctrl+C that missed the child tree, a crashed
# shell, etc.) can leave a runserver/uvicorn holding the port. A fresh server
# would then fail to bind and the stack would look "up" while serving nothing,
# which is worse than failing loudly. Find and stop the squatter first.
function Get-PortOwnerPids([int]$LocalPort) {
    $pids = @()
    try {
        $conns = Get-NetTCPConnection -LocalPort $LocalPort -State Listen -ErrorAction SilentlyContinue
        foreach ($c in $conns) { if ($c.OwningProcess) { $pids += [int]$c.OwningProcess } }
    }
    catch {
        # Fall back to netstat on hosts/PowerShell builds without the cmdlet.
        $lines = (netstat -ano -p tcp 2>$null | Select-String -Pattern ":$LocalPort\s" | Select-String "LISTENING")
        foreach ($line in $lines) {
            $parts = ($line.ToString().Trim() -split "\s+")
            if ($parts.Count -ge 5 -and $parts[-1] -match "^\d+$") { $pids += [int]$parts[-1] }
        }
    }
    return ($pids | Sort-Object -Unique)
}

if (-not $NoWeb) {
    $squatters = Get-PortOwnerPids -LocalPort $Port
    foreach ($squatPid in $squatters) {
        # Only ever kill this project's own Python, never an unrelated service.
        $procInfo = Get-CimInstance Win32_Process -Filter "ProcessId=$squatPid" -ErrorAction SilentlyContinue
        $cmdLine = if ($procInfo) { [string]$procInfo.CommandLine } else { "" }
        $ownPython = $cmdLine -like "*$Root*" -or $cmdLine -like "*$py*"
        if ($squatPid -eq $PID -or -not $ownPython) {
            Write-Host ("    ! port {0} is held by PID {1} but it is not this project's " -f $Port, $squatPid) -ForegroundColor Red
            Write-Host "      Python (or it is this shell). Refusing to kill it." -ForegroundColor Red
            Write-Host "      Free the port manually, or pick another with -Port." -ForegroundColor Red
            exit 1
        }
        Write-Host ("  - clearing stale listener on port {0} (PID {1})" -f $Port, $squatPid) -ForegroundColor Yellow
        & taskkill /PID $squatPid /T /F 2>$null | Out-Null
    }
    if ($squatters.Count -gt 0) {
        # Give the OS a moment to release the socket before rebinding.
        Start-Sleep -Milliseconds 800
    }
}

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
        # --noreload: the auto-reloader forks a second process per worker, which
        # on Windows is a common source of orphaned children that survive
        # Ctrl+C and then squat on the port. We do not need reload here because
        # the whole stack is restarted to pick up changes.
        Start-StackProcess -Name "web" -File $py -Arguments @(
            "manage.py", "runserver", "$Host_`:$Port", "--noreload"
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

# --- MT5 worker (opt-in) ----------------------------------------------------
# The MT5 worker is a separate host by default (it needs a live Windows
# terminal). With -WithMT5 we start it here, but only after a BOUNDED preflight
# proves the terminal is actually reachable. Without that, a machine with no
# logged-in terminal would spawn a worker that dies immediately (or hangs),
# and the stack would look "up" while market data silently stayed stale.
$mt5Status = "not requested"
if ($WithMT5) {
    $mt5ProbeLog = Join-Path $logDir "mt5-preflight.log"
    Write-Host ("`n==> MT5 preflight (<= {0}s) ..." -f $MT5ProbeTimeoutSeconds) -ForegroundColor Cyan

    # Bound the native connect: a tiny per-attempt timeout plus no retries, so
    # the child cannot sit inside the MT5 API for minutes (the failure mode
    # seen with mt5_integration_check). The hard kill below is the backstop.
    $probeEnv = @{
        MT5_TIMEOUT_MS          = "5000"
        MT5_MAX_RETRIES         = "0"
        MT5_RETRY_BACKOFF_SECONDS = "0"
    }
    $prevEnv = @{}
    foreach ($k in $probeEnv.Keys) {
        $prevEnv[$k] = [Environment]::GetEnvironmentVariable($k, "Process")
        [Environment]::SetEnvironmentVariable($k, $probeEnv[$k], "Process")
    }

    $probe = Start-Process -FilePath $py `
        -ArgumentList @("manage.py", "mt5_worker", "--once", "--collector", "mt5-preflight") `
        -WorkingDirectory $Root -NoNewWindow -PassThru `
        -RedirectStandardOutput $mt5ProbeLog -RedirectStandardError "$mt5ProbeLog.err"

    $finished = $probe.WaitForExit($MT5ProbeTimeoutSeconds * 1000)
    if (-not $finished) {
        & taskkill /PID $probe.Id /T /F 2>$null | Out-Null
        $mt5Status = "unreachable"
        Write-Host ("    MT5 did not connect within {0}s - NOT starting the worker." -f $MT5ProbeTimeoutSeconds) -ForegroundColor Red
    }
    else {
        # Even after Refresh(), Start-Process -PassThru can report a blank
        # ExitCode on some Windows/PowerShell builds, so success is judged on
        # the worker's own evidence: it logs "mt5.connect.success" only after a
        # real handshake, and prints a CommandError to stderr on failure.
        try { $probe.Refresh() } catch { }
        $probeExit = $probe.ExitCode
        $probeOut = (Get-Content $mt5ProbeLog -Raw -ErrorAction SilentlyContinue)
        $probeErr = (Get-Content "$mt5ProbeLog.err" -Raw -ErrorAction SilentlyContinue)
        $connected = ($probeOut -match "MT5 worker .* starting:") -and
            ($probeErr -match "mt5\.connect\.success") -and
            ($probeErr -notmatch "Could not connect to MT5")

        if ($connected -or $probeExit -eq 0) {
            $mt5Status = "ready"
            Write-Host "    MT5 preflight connected - starting the worker." -ForegroundColor Green
        }
        else {
            $mt5Status = "unreachable"
            $reason = if ($null -ne $probeExit) { "exit $probeExit" } else { "no successful handshake" }
            Write-Host ("    MT5 preflight failed ({0}) - NOT starting the worker." -f $reason) -ForegroundColor Red
        }
    }

    # Restore the environment so the real worker uses the normal settings.
    foreach ($k in $probeEnv.Keys) {
        [Environment]::SetEnvironmentVariable($k, $prevEnv[$k], "Process")
    }

    if ($mt5Status -eq "ready") {
        # The heartbeat id is what the dashboard reads, so a stable, readable
        # id (not worker-<pid>) is used here.
        Start-StackProcess -Name "mt5-worker" -File $py -Arguments @(
            "manage.py", "mt5_worker", "--collector", "mt5-worker"
        )
    }
    else {
        Write-Host "    Last lines of the preflight log:" -ForegroundColor DarkGray
        Get-Content $mt5ProbeLog -Tail 6 -ErrorAction SilentlyContinue |
            ForEach-Object { Write-Host "      $_" -ForegroundColor DarkGray }
        Get-Content "$mt5ProbeLog.err" -Tail 6 -ErrorAction SilentlyContinue |
            ForEach-Object { Write-Host "      $_" -ForegroundColor DarkGray }
        Write-Host "    Market data will stay stale until MT5 connects. The rest" -ForegroundColor Yellow
        Write-Host "    of the stack is starting normally." -ForegroundColor Yellow
    }
}

# --- Verify -----------------------------------------------------------------
# Do not announce success on faith. Wait for the web server to actually answer
# (a bound port that returns nothing is exactly the failure mode this guards)
# and confirm no child died at startup. Anything wrong is reported loudly and
# the exit code is non-zero so a supervisor/CI can see it too.
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

function Test-WebResponding {
    param([string]$ProbeHost, [int]$ProbePort, [int]$TimeoutSeconds = 25)
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $client = New-Object System.Net.Sockets.TcpClient
            $client.Connect($ProbeHost, $ProbePort)
            if ($client.Connected) { $client.Close(); return $true }
            $client.Close()
        }
        catch { }
        Start-Sleep -Milliseconds 500
    }
    return $false
}

$failed = @()

# Give children a moment to settle before judging them.
Start-Sleep -Seconds 3
foreach ($entry in $script:processes) {
    if ($entry.Proc -and $entry.Proc.HasExited) {
        $failed += ("{0} exited early (code {1}); see {2}" -f `
                $entry.Name, $entry.Proc.ExitCode, $entry.Log)
    }
}

if (-not $NoWeb) {
    Write-Host ("`n==> Waiting for web on {0}:{1} ..." -f $Host_, $Port) -ForegroundColor Cyan
    if (Test-WebResponding -ProbeHost $Host_ -ProbePort $Port) {
        Write-Host "    web is accepting connections" -ForegroundColor Green
    }
    else {
        $failed += "web did not accept connections on ${Host_}:${Port} within 25s; see $logDir\web.log"
    }
}

if ($failed.Count -gt 0) {
    Write-Host "`n==> NOT fully up:" -ForegroundColor Red
    foreach ($msg in $failed) { Write-Host "    - $msg" -ForegroundColor Red }
    Write-Host "`n    Stopping the processes that did start...`n" -ForegroundColor Yellow
    Stop-All
    exit 1
}

# --- Report -----------------------------------------------------------------
Write-Host "`n==> Stack is up. $($processes.Count) process(es)." -ForegroundColor Green
if (-not $NoWeb) {
    $scheme = "http"
    Write-Host ("    Web: {0}://{1}:{2}/  ({3})" -f $scheme, $Host_, $Port, $webMode) -ForegroundColor Green
}
if ($WithMT5) {
    if ($mt5Status -eq "ready") {
        Write-Host "    MT5 worker: running (market data should update)" -ForegroundColor Green
    }
    else {
        Write-Host "    MT5 worker: NOT running - market data will stay stale" -ForegroundColor Red
        Write-Host "                (log the MT5 terminal in, then re-run)" -ForegroundColor Red
    }
}
else {
    Write-Host "    MT5 worker: not started (pass -WithMT5 to include it)" -ForegroundColor DarkGray
}
Write-Host "    Logs: $logDir" -ForegroundColor Green
Write-Host "    Press Ctrl+C to stop everything.`n" -ForegroundColor Green

# --- Watch: restart nothing, but surface an early death quickly -------------
# Names already reported as dead, so a crashed child is announced once and its
# warning is not lost to the periodic Clear-Host.
$reportedDead = @{}

try {
    while ($true) {
        foreach ($entry in $script:processes) {
            if ($entry.Proc.HasExited -and -not $reportedDead.ContainsKey($entry.Name)) {
                $reportedDead[$entry.Name] = $true
                if ($entry.Name -eq "mt5-worker") {
                    Write-Host "`nWARN: mt5-worker exited (code $($entry.Proc.ExitCode)). Market data has stopped updating. See $($entry.Log)" -ForegroundColor Red
                }
                else {
                    Write-Host ("`nWARN: {0} exited early (code {1}). See {2}" -f `
                            $entry.Name, $entry.Proc.ExitCode, $entry.Log) -ForegroundColor Red
                }
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
