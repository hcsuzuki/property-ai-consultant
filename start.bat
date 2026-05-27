@echo off
chcp 65001 > nul
echo AI Property Investment Consultant - Starting...
echo.

REM Python executable path
set PYTHON=C:\Users\c_73a\AppData\Local\Python\pythoncore-3.14-64\python.exe
set STREAMLIT=C:\Users\c_73a\AppData\Local\Python\pythoncore-3.14-64\Scripts\streamlit.exe

REM Check Python
if not exist "%PYTHON%" (
    echo [ERROR] Python not found. Please check the PYTHON path in this script.
    pause
    exit /b 1
)

REM Check .env
if not exist .env (
    echo [WARNING] .env file not found.
    echo Please copy .env.example to .env and set your API keys.
    echo.
    copy .env.example .env
    echo Created .env from template. Open it and fill in your API keys.
    notepad .env
    pause
    exit /b 1
)

REM Install dependencies
echo Installing/checking dependencies...
"%PYTHON%" -m pip install -r requirements.txt --quiet

REM Launch Streamlit
echo.
echo Launching at http://localhost:8501
echo.
"%PYTHON%" -m streamlit run app.py --server.port 8501

pause
