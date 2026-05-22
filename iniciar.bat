@echo off
echo ====================================
echo   FEFO WMS Control - Iniciando...
echo ====================================

REM Verifica Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ERRO: Python nao encontrado. Instale em https://python.org
    pause
    exit /b 1
)

REM Instala dependencias se necessario
if not exist "venv" (
    echo Criando ambiente virtual...
    python -m venv venv
)

call venv\Scripts\activate.bat

echo Instalando dependencias...
pip install -r requirements.txt -q

REM Descobre IP local
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /i "IPv4"') do (
    set IP=%%a
    goto found
)
:found
set IP=%IP: =%

echo.
echo ====================================
echo  Sistema iniciado com sucesso!
echo  Acesse no navegador:
echo  http://localhost:8000
echo  http://%IP%:8000  (outros PCs da rede)
echo ====================================
echo.

uvicorn main:app --host 0.0.0.0 --port 8000 --reload

pause
