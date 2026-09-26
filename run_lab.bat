@echo off
setlocal
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  python -m venv .venv
  .venv\Scripts\python -m pip install -U pip
  .venv\Scripts\pip install -r requirements.txt
)
echo.
echo Starting CellForge lab ...
echo Leave this window open and open the URL in your browser.
echo.
.venv\Scripts\python cellforge.py lab --host 0.0.0.0 --port 8000
endlocal
