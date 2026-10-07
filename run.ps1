# Start DriftGuard. AI is optional: set ANTHROPIC_API_KEY and DRIFTGUARD_CLAUDE_MODEL to enable it.
# Usage: .\run.ps1 [-Port 8000] [-Demo]
param([int]$Port = 8000, [switch]$Demo)

Set-Location $PSScriptRoot
if (Test-Path .env) {
  Get-Content .env | Where-Object { $_ -match '^\s*[A-Za-z_][A-Za-z0-9_]*\s*=' } | ForEach-Object {
    $k, $v = $_ -split '=', 2
    Set-Item -Path "Env:$($k.Trim())" -Value $v.Trim().Trim('"')
  }
}
if ($Demo) { $env:DRIFTGUARD_DEMO_MODE = "1" }

python -c "import fastapi, uvicorn" 2>$null
if ($LASTEXITCODE -ne 0) { Write-Host "Installing dependencies..."; python -m pip install -q -r backend/requirements.txt }

if ($env:ANTHROPIC_API_KEY -and $env:DRIFTGUARD_CLAUDE_MODEL) { Write-Host "AI: enabled" }
elseif ($env:DRIFTGUARD_DEMO_MODE -eq "1") { Write-Host "AI: demo stub" }
else { Write-Host "AI: off (set ANTHROPIC_API_KEY and DRIFTGUARD_CLAUDE_MODEL to enable). Deterministic checks run normally." }

Write-Host "Open http://127.0.0.1:$Port  (health: /health)"
python -m uvicorn backend.src.app:app --host 127.0.0.1 --port $Port
