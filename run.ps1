# Start DriftGuard. AI is optional: set DRIFTGUARD_AI_PROVIDER, DRIFTGUARD_AI_MODEL and the provider key to enable it.
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
# OCR for image-only PDFs: on by default; it only takes effect once pytesseract, pypdfium2 and the Tesseract binary are installed.
if (-not $env:DRIFTGUARD_OCR) { $env:DRIFTGUARD_OCR = "1" }

python -c "import fastapi, uvicorn" 2>$null
if ($LASTEXITCODE -ne 0) { Write-Host "Installing dependencies..."; python -m pip install -q -r backend/requirements.txt }

$aiProvider = $env:DRIFTGUARD_AI_PROVIDER
$aiModel = $env:DRIFTGUARD_AI_MODEL
if (-not $aiProvider -and $env:DRIFTGUARD_SEMANTIC_PROVIDER -eq "claude") { $aiProvider = "anthropic" }
if (-not $aiModel -and $aiProvider -eq "anthropic") { $aiModel = $env:DRIFTGUARD_CLAUDE_MODEL }
if ($env:DRIFTGUARD_SEMANTIC_PROVIDER -or $env:DRIFTGUARD_CLAUDE_MODEL) { Write-Host "WARNING: DRIFTGUARD_SEMANTIC_PROVIDER / DRIFTGUARD_CLAUDE_MODEL are deprecated; use DRIFTGUARD_AI_PROVIDER and DRIFTGUARD_AI_MODEL." }
$keyVar = switch ($aiProvider) { "anthropic" { "ANTHROPIC_API_KEY" } "openai" { "OPENAI_API_KEY" } "openrouter" { "OPENROUTER_API_KEY" } default { $null } }
if ($aiProvider -and $aiProvider -ne "disabled" -and $aiModel -and $keyVar -and (Get-Item "Env:$keyVar" -ErrorAction SilentlyContinue)) { Write-Host "AI: enabled ($aiProvider)" }
elseif ($env:DRIFTGUARD_DEMO_MODE -eq "1") { Write-Host "AI: demo stub" }
else { Write-Host "AI: off (set DRIFTGUARD_AI_PROVIDER, DRIFTGUARD_AI_MODEL and the provider key to enable). Deterministic checks run normally." }

Write-Host "Open http://127.0.0.1:$Port  (health: /health)"
python -m uvicorn backend.src.app:app --host 127.0.0.1 --port $Port
