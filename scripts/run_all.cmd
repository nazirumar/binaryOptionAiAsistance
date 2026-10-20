@echo off
REM scripts\run_all.cmd
REM ---------------------------------------------------------------------------
REM CMD entry point for scripts\run_all.ps1 - start the whole local stack from
REM a plain Command Prompt (cmd.exe), no PowerShell window required.
REM
REM   scripts\run_all.cmd
REM   scripts\run_all.cmd -WithMT5
REM   scripts\run_all.cmd -NoWeb -Port 8010
REM
REM Any arguments are forwarded verbatim to run_all.ps1. Ctrl+C stops the stack.
REM
REM Requires Windows PowerShell (present on every supported Windows). Nothing
REM here reads, prints or writes secrets.
REM ---------------------------------------------------------------------------

setlocal

REM Run next to this script regardless of the caller's current directory.
set "SCRIPT_DIR=%~dp0"

REM Prefer Windows PowerShell (powershell.exe). Fall back to pwsh if present.
where powershell.exe >nul 2>nul
if %ERRORLEVEL%==0 (
    set "PS=powershell.exe"
) else (
    where pwsh.exe >nul 2>nul
    if %ERRORLEVEL%==0 (
        set "PS=pwsh.exe"
    ) else (
        echo ERROR: neither powershell.exe nor pwsh.exe was found on PATH. 1>&2
        exit /b 1
    )
)

REM -ExecutionPolicy Bypass so a Restricted policy on this machine does not
REM block the launcher; -NoProfile keeps the run reproducible; -NoLogo trims
REM the banner. %* forwards every argument unchanged.
"%PS%" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%run_all.ps1" %*

REM Propagate the PowerShell exit code so a supervisor/CI sees failures too.
set "RC=%ERRORLEVEL%"
endlocal & exit /b %RC%
