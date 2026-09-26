@echo off
setlocal
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  python -m venv .venv
  .venv\Scripts\python -m pip install -U pip
  .venv\Scripts\pip install -r requirements.txt
)
.venv\Scripts\python run_project.py %*
echo.
echo Open docs\REPORT.html and docs\SLIDES.html
endlocal
