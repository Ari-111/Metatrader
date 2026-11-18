Set-Location (Split-Path $PSScriptRoot -Parent)
python -P -m uvicorn server.app:app --host 127.0.0.1 --port 8000
