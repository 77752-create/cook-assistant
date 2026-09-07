$ErrorActionPreference = "SilentlyContinue"
$base = $PSScriptRoot

# Find a signed Python (the bundled runtime is blocked by Smart App Control)
$pyw = "D:\Python\pythonw.exe"
$candidates = @(
    "D:\Python\pythonw.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python313\pythonw.exe",
    "C:\Python313\pythonw.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python312\pythonw.exe",
    "C:\Python312\pythonw.exe"
)
foreach ($p in $candidates) {
    if (Test-Path $p) { $pyw = $p; break }
}

# Start the server only if it is not already running
$listening = Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue
if (-not $listening) {
    Start-Process -FilePath $pyw -ArgumentList "app.py" -WorkingDirectory $base -WindowStyle Hidden
    Start-Sleep -Seconds 5
}

# Open the browser
Start-Process "http://127.0.0.1:8765"
