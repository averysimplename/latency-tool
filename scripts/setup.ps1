$ErrorActionPreference = "Stop"

py -m venv myenv

# Activate
. .\myenv\Scripts\Activate.ps1

python -m pip install --upgrade pip
pip install -r requirements.txt

Write-Host ""
Write-Host "✅ Setup complete."
Write-Host "Run: .\myenv\Scripts\Activate.ps1 ; python run.py"
