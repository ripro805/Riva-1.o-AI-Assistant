@echo off
setlocal

REM Always run from this script's folder
cd /d "%~dp0"

REM Activate venv if it exists
if exist ".venv\Scripts\activate.bat" (
  call ".venv\Scripts\activate.bat"
)

python .\main.py --text

endlocal
