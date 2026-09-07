@echo off
cd /d "%~dp0"

where pyw >nul 2>&1
if not errorlevel 1 (
  set "PYW=pyw"
  set "PYW_ARGS=-3"
) else (
  set "PYW=pythonw"
  set "PYW_ARGS="
)

rem If the server is already running, just open the browser
netstat -ano | findstr ":8765" | findstr "LISTENING" >nul
if not errorlevel 1 goto open

start "" "%PYW%" %PYW_ARGS% "app.py"
timeout /t 3 /nobreak >nul

:open
start "" "http://127.0.0.1:8765"
exit
