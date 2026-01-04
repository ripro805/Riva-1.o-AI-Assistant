@echo off
setlocal

REM Always run from this script's folder
cd /d "%~dp0"

REM Activate venv if it exists
if exist ".venv\Scripts\activate.bat" (
  call ".venv\Scripts\activate.bat"
)

REM Optional: pin a fixed Chrome profile (prevents the profile picker).
REM Examples: "Default", "Profile 1", "Profile 2"
REM set "RIVA_CHROME_PROFILE_DIR=Default"

python .\main.py --text

endlocal
