@echo off
REM Script para iniciar apenas Django (Windows)
REM Use se você já tem Ollama+Proxy rodando externamente

echo ======================================
echo 🚀 COLMOL - Iniciando Django
echo ======================================

REM Verificar Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ❌ Python não encontrado. Instale Python 3.11+
    pause
    exit /b 1
)

REM Instalar dependências Python
echo 📦 Instalando dependências Python...
pip install -r requirements.txt -q

REM Configurar variáveis de ambiente
set OLLAMA_API_URL=http://localhost:3000
set OLLAMA_MODEL=llava:latest

echo.
echo ✅ Django Server iniciado!
echo ======================================
echo Django:  http://localhost:5000
echo.
echo ⚠️  Certifique-se que Ollama e Proxy estão rodando:
echo    Ollama: http://localhost:8000
echo    Proxy:  http://localhost:3000
echo ======================================
echo.

python manage.py runserver 0.0.0.0:5000
