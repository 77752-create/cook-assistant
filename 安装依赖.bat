@echo off
cd /d "%~dp0"
chcp 65001 >nul

set "PYTHON=D:\Python\python.exe"
if not exist "%PYTHON%" set "PYTHON=C:\Users\%USERNAME%\AppData\Local\Programs\Python\Python313\python.exe"
if not exist "%PYTHON%" set "PYTHON=C:\Python313\python.exe"
if not exist "%PYTHON%" set "PYTHON=C:\Users\%USERNAME%\AppData\Local\Programs\Python\Python312\python.exe"
if not exist "%PYTHON%" set "PYTHON=C:\Python312\python.exe"
if not exist "%PYTHON%" set "PYTHON=python"

echo 正在安装做菜助手依赖，请保持网络连接...
"%PYTHON%" -m pip install --upgrade pip
if errorlevel 1 goto failed
"%PYTHON%" -m pip install -r requirements.txt
if errorlevel 1 goto failed
echo.
echo 安装完成。现在可以双击“启动做菜助手.bat”。
pause
exit /b 0

:failed
echo.
echo 安装失败。请确认已安装 Python 3.12 或 3.13，并勾选了 Add Python to PATH。
pause
exit /b 1
