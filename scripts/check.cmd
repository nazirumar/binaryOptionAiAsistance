@echo off
REM scripts\check.cmd
REM ---------------------------------------------------------------------------
REM CMD entry point for scripts\check.ps1 - run the full quality gate from a
REM plain Command Prompt (cmd.exe).
REM
REM   scripts\check.cmd
REM
REM Any arguments are forwarded verbatim to check.ps1.
REM ---------------------------------------------------------------------------

setlocal
set "SCRIPT_DIR=%~dp0"

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

"%PS%" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%check.ps1" %*

set "RC=%ERRORLEVEL%"
endlocal & exit /b %RC%
