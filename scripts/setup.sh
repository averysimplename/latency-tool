#!/usr/bin/env bash
set -euo pipefail

python3 -m venv myenv

# Activate
if [ -f "myenv/bin/activate" ]; then
  source myenv/bin/activate
else
  echo "Could not find venv activate script. Are you on Windows without WSL/Git Bash?"
  exit 1
fi

python -m pip install --upgrade pip
pip install -r requirements.txt

echo ""
echo "✅ Setup complete."
echo "Run: source myenv/bin/activate && python run.py"
