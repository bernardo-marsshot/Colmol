#!/bin/bash
# Script para iniciar apenas Django (Linux/Mac)
# Use se você já tem Ollama+Proxy rodando externamente

set -e

echo "======================================"
echo "🚀 COLMOL - Iniciando Django"
echo "======================================"

# Verificar Python
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 não encontrado. Instale Python 3.11+"
    exit 1
fi

# Instalar dependências Python
echo "📦 Instalando dependências Python..."
pip3 install -r requirements.txt -q

# Configurar variáveis de ambiente
export OLLAMA_API_URL="http://localhost:3000"
export OLLAMA_MODEL="llava:latest"

echo ""
echo "✅ Django Server iniciado!"
echo "======================================"
echo "Django:  http://localhost:5000"
echo ""
echo "⚠️  Certifique-se que Ollama e Proxy estão rodando:"
echo "   Ollama: http://localhost:8000"
echo "   Proxy:  http://localhost:3000"
echo "======================================"
echo ""

python3 manage.py runserver 0.0.0.0:5000
