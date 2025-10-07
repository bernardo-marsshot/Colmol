@echo off
REM Script para iniciar COLMOL localmente (Windows)
REM Inicia: Ollama Server + Node.js Proxy + Django

echo ======================================
echo 🚀 COLMOL - Iniciando Servidores
echo ======================================

REM Verificar Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ❌ Python não encontrado. Instale Python 3.11+
    pause
    exit /b 1
)

REM Verificar Node.js
node --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ❌ Node.js não encontrado. Instale Node.js 20+
    pause
    exit /b 1
)

REM Verificar Ollama
ollama --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ⚠️  Ollama não encontrado. Ollama Vision será desabilitado.
    echo    Para instalar: https://ollama.ai/download
    set SKIP_OLLAMA=1
) else (
    echo ✅ Ollama encontrado
    set SKIP_OLLAMA=0
)

REM Instalar dependências Python
echo.
echo 📦 Instalando dependências Python...
pip install -r requirements.txt -q

REM Instalar dependências Node.js
echo 📦 Instalando dependências Node.js...
call npm install --silent

REM Configurar variáveis de ambiente
set OLLAMA_API_URL=http://localhost:3000
set OLLAMA_MODEL=llava:latest
set OLLAMA_HOST=0.0.0.0:8000
set OLLAMA_NUM_PARALLEL=1
set OLLAMA_MAX_QUEUE=64
set OLLAMA_KEEP_ALIVE=5m

REM Iniciar Ollama (se disponível)
if %SKIP_OLLAMA%==0 (
    echo.
    echo 🤖 Iniciando Ollama Server na porta 8000...
    taskkill /F /IM ollama.exe >nul 2>&1
    start /B ollama serve
    timeout /t 3 >nul
    
    echo 📥 Verificando modelo llava:latest...
    ollama list | findstr "llava:latest" >nul
    if %errorlevel% neq 0 (
        echo ⬇️  Baixando modelo llava:latest ^(pode demorar^)...
        ollama pull llava:latest
    )
)

REM Iniciar Node.js Proxy
echo.
echo 🌐 Iniciando Node.js Proxy na porta 3000...
start /B node server.js
timeout /t 2 >nul

REM Iniciar Django
echo.
echo 🐍 Iniciando Django Server na porta 5000...
echo.
echo ======================================
echo ✅ Servidores iniciados!
echo ======================================
echo Django:  http://localhost:5000
echo Proxy:   http://localhost:3000
if %SKIP_OLLAMA%==0 (
    echo Ollama:  http://localhost:8000
)
echo.
echo Pressione Ctrl+C para parar todos os servidores
echo ======================================
echo.

python manage.py runserver 0.0.0.0:5000
