@echo off
cd /d "%~dp0"
chcp 65001 >nul

where py >nul 2>&1
if not errorlevel 1 (
  set "PYTHON=py.exe"
  set "PYTHON_ARGS=-3"
) else (
  set "PYTHON=python"
  set "PYTHON_ARGS="
)

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
"%PYTHON%" %PYTHON_ARGS% app.py
echo.
echo Server stopped.
pause

:open
start "" "http://127.0.0.1:8765"
exit
