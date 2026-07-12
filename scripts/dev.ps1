# Start the classifier service for development (Windows).
$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path "$PSScriptRoot\..").Path
Set-Location $repoRoot
& python -m uvicorn classifier.main:app --reload --host 127.0.0.1 --port 8765