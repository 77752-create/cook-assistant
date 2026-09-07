@echo off
chcp 65001 >nul
echo 正在停止做菜助手...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8765" ^| findstr "LISTENING"') do taskkill /f /pid %%a >nul 2>&1
echo 已停止。可以关闭本窗口。
pause
