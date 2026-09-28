@echo off
setlocal
cd /d %~dp0
echo [CareerOS] Preparing backend...
cd backend
if not exist .venv (py -3.13 -m venv .venv)
call .venv\Scripts\activate.bat
python -m pip install -q --upgrade pip
pip install -q -r requirements.txt
python -m scripts.init_db
python -m scripts.seed_demo
start "CareerOS Backend" cmd /k "cd /d %~dp0backend && call .venv\Scripts\activate.bat && uvicorn app.main:app --reload"
cd ..\frontend
echo [CareerOS] Preparing frontend...
if not exist node_modules call npm install
start "CareerOS Frontend" cmd /k "cd /d %~dp0frontend && npm run dev"
echo.
echo CareerOS is starting. Open http://localhost:3000
timeout /t 4 >nul
start http://localhost:3000
endlocal
