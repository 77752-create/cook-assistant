@echo off
cd /d "%~dp0"
chcp 65001 >nul

rem Prefer the officially installed Python (signed, not blocked by Smart App Control)
set "PYTHON=D:\Python\python.exe"
if not exist "%PYTHON%" set "PYTHON=C:\Users\deng\AppData\Local\Programs\Python\Python313\python.exe"
if not exist "%PYTHON%" set "PYTHON=C:\Python313\python.exe"
if not exist "%PYTHON%" set "PYTHON=C:\Users\deng\AppData\Local\Programs\Python\Python312\python.exe"
if not exist "%PYTHON%" set "PYTHON=C:\Python312\python.exe"
if not exist "%PYTHON%" set "PYTHON=C:\Users\deng\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if not exist "%PYTHON%" set "PYTHON=python"

echo.
echo Starting Cook Assistant ...
echo If the browser does not open automatically, open this URL manually:
echo   http://127.0.0.1:8765
echo.

rem If the server is already running, just open the browser
netstat -ano | findstr ":8765" | findstr "LISTENING" >nul
if not errorlevel 1 goto open

rem Open the browser first, then start the server in the foreground (this window shows logs)
start "" "http://127.0.0.1:8765"
"%PYTHON%" app.py
echo.
echo Server stopped.
pause

:open
start "" "http://127.0.0.1:8765"
exit
