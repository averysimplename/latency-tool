macOS

chmod +x scripts/setup.sh scripts/run.sh
./scripts/setup.sh
./scripts/run.sh


Windows

Set-ExecutionPolicy -Scope Process Bypass
.\scripts\setup.ps1
.\scripts\run.ps1


############

doctor.py now works if you want to check that your system is ready to rock and roll:

python3 doctor.py
