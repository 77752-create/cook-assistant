$ErrorActionPreference = "SilentlyContinue"
$base = $PSScriptRoot

$pyw = (Get-Command pyw.exe -ErrorAction SilentlyContinue).Source
if (-not $pyw) { $pyw = (Get-Command pythonw.exe -ErrorAction SilentlyContinue).Source }
if (-not $pyw) {
    Write-Error "未找到 Python。请先安装 Python 3.12 或 3.13，并勾选 Add Python to PATH。"
    exit 1
}

# Start the server only if it is not already running
$listening = Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue
if (-not $listening) {
    Start-Process -FilePath $pyw -ArgumentList "app.py" -WorkingDirectory $base -WindowStyle Hidden
    Start-Sleep -Seconds 5
}

# Open the browser
Start-Process "http://127.0.0.1:8765"
