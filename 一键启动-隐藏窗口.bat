@echo off
cd /d "%~dp0"

rem Prefer the officially installed Python (signed, not blocked by Smart App Control)
set "PYW=D:\Python\pythonw.exe"
if not exist "%PYW%" set "PYW=C:\Users\deng\AppData\Local\Programs\Python\Python313\pythonw.exe"
if not exist "%PYW%" set "PYW=C:\Python313\pythonw.exe"
if not exist "%PYW%" set "PYW=C:\Users\deng\AppData\Local\Programs\Python\Python312\pythonw.exe"
if not exist "%PYW%" set "PYW=C:\Python312\pythonw.exe"
if not exist "%PYW%" set "PYW=C:\Users\deng\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\pythonw.exe"
if not exist "%PYW%" set "PYW=pythonw"

rem If the server is already running, just open the browser
netstat -ano | findstr ":8765" | findstr "LISTENING" >nul
if not errorlevel 1 goto open

start "" "%PYW%" "app.py"
timeout /t 3 /nobreak >nul

:open
start "" "http://127.0.0.1:8765"
exit
