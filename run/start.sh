#!/bin/bash
# Script para iniciar COLMOL localmente (Linux/Mac)
# Inicia: Ollama Server + Node.js Proxy + Django

set -e

echo "======================================"
echo "🚀 COLMOL - Iniciando Servidores"
echo "======================================"

# Verificar Python
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 não encontrado. Instale Python 3.11+"
    exit 1
fi

# Verificar Node.js
if ! command -v node &> /dev/null; then
    echo "❌ Node.js não encontrado. Instale Node.js 20+"
    exit 1
fi

# Verificar Ollama
if ! command -v ollama &> /dev/null; then
    echo "⚠️  Ollama não encontrado. Ollama Vision será desabilitado."
    echo "   Para instalar: https://ollama.ai/download"
    SKIP_OLLAMA=1
else
    echo "✅ Ollama encontrado"
    SKIP_OLLAMA=0
fi

# Instalar dependências Python
echo ""
echo "📦 Instalando dependências Python..."
pip3 install -r requirements.txt -q

# Instalar dependências Node.js
echo "📦 Instalando dependências Node.js..."
npm install --silent

# Configurar variáveis de ambiente
export OLLAMA_API_URL="http://localhost:3000"
export OLLAMA_MODEL="llava:latest"
export OLLAMA_HOST="0.0.0.0:8000"
export OLLAMA_NUM_PARALLEL=1
export OLLAMA_MAX_QUEUE=64
export OLLAMA_KEEP_ALIVE=5m

# Iniciar Ollama (se disponível)
if [ $SKIP_OLLAMA -eq 0 ]; then
    echo ""
    echo "🤖 Iniciando Ollama Server na porta 8000..."
    pkill ollama 2>/dev/null || true
    ollama serve &
    OLLAMA_PID=$!
    sleep 3
    
    echo "📥 Verificando modelo llava:latest..."
    if ! ollama list | grep -q "llava:latest"; then
        echo "⬇️  Baixando modelo llava:latest (pode demorar)..."
        ollama pull llava:latest
    fi
fi

# Iniciar Node.js Proxy
echo ""
echo "🌐 Iniciando Node.js Proxy na porta 3000..."
node server.js &
PROXY_PID=$!
sleep 2

# Iniciar Django
echo ""
echo "🐍 Iniciando Django Server na porta 5000..."
echo ""
echo "======================================"
echo "✅ Servidores iniciados!"
echo "======================================"
echo "Django:  http://localhost:5000"
echo "Proxy:   http://localhost:3000"
if [ $SKIP_OLLAMA -eq 0 ]; then
    echo "Ollama:  http://localhost:8000"
fi
echo ""
echo "Pressione Ctrl+C para parar todos os servidores"
echo "======================================"
echo ""

python3 manage.py runserver 0.0.0.0:5000

# Cleanup ao sair
trap "echo ''; echo 'Parando servidores...'; kill $PROXY_PID 2>/dev/null; [ $SKIP_OLLAMA -eq 0 ] && kill $OLLAMA_PID 2>/dev/null; exit" INT TERM
