# LogicGate one-click launcher (PowerShell variant).
# Right-click -> "Run with PowerShell", or pin to Start menu.
$Host.UI.RawUI.WindowTitle = "LogicGate Server"
Set-Location $PSScriptRoot

Write-Host "Starting LogicGate..." -ForegroundColor Cyan
Write-Host ""

# Open browser ~3 seconds after Flask starts.
Start-Job -ScriptBlock {
  Start-Sleep -Seconds 3
  Start-Process "http://localhost:5000"
} | Out-Null

# Run Flask in foreground; Ctrl+C or closing the window stops the server.
python app.py

if ($LASTEXITCODE -ne 0) {
  Write-Host ""
  Write-Host "Server stopped with an error. Press any key." -ForegroundColor Yellow
  $null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
}
