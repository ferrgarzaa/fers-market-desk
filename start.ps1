# Starts backend (FastAPI on :8000) and frontend (Vite on :5173). Windows PowerShell.
Set-Location $PSScriptRoot
if (-not (Test-Path backend\.venv)) {
  python -m venv backend\.venv
  backend\.venv\Scripts\pip install -r backend\requirements-dev.txt
}
if (-not (Test-Path frontend\node_modules)) { Push-Location frontend; npm install; Pop-Location }
$back = Start-Process -PassThru -NoNewWindow -WorkingDirectory backend `
  -FilePath "$PSScriptRoot\backend\.venv\Scripts\python.exe" -ArgumentList "-m","uvicorn","app.main:app","--port","8000"
try { Push-Location frontend; npm run dev } finally { Stop-Process -Id $back.Id; Pop-Location }
