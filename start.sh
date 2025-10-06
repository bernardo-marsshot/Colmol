#!/bin/bash

echo "🚀 Starting Ollama + Proxy Server..."

export OLLAMA_HOST=0.0.0.0:8000
export OLLAMA_NUM_PARALLEL=1
export OLLAMA_MAX_QUEUE=64
export OLLAMA_KEEP_ALIVE=5m
export OLLAMA_ORIGINS="*"

echo "📦 Environment variables:"
echo "  OLLAMA_HOST=$OLLAMA_HOST"
echo "  OLLAMA_NUM_PARALLEL=$OLLAMA_NUM_PARALLEL"
echo "  OLLAMA_MAX_QUEUE=$OLLAMA_MAX_QUEUE"
echo "  OLLAMA_KEEP_ALIVE=$OLLAMA_KEEP_ALIVE"

if pgrep -x "ollama" > /dev/null; then
    echo "⚠️  Ollama already running, killing existing process..."
    pkill -9 ollama
    sleep 2
fi

echo "🔧 Starting Ollama server (CPU-only, mmap enabled, parallel=1)..."
ollama serve > /tmp/ollama.log 2>&1 &
OLLAMA_PID=$!
echo "  Ollama PID: $OLLAMA_PID"

echo "⏳ Waiting for Ollama to be ready on port 8000..."
for i in {1..30}; do
  if curl -s http://127.0.0.1:8000/api/tags > /dev/null 2>&1; then
    echo "✅ Ollama is ready!"
    break
  fi
  echo "  Attempt $i/30..."
  sleep 2
done

if ! curl -s http://127.0.0.1:8000/api/tags > /dev/null 2>&1; then
  echo "❌ Ollama failed to start. Check /tmp/ollama.log"
  tail -20 /tmp/ollama.log
  exit 1
fi

echo "📊 Available models:"
curl -s http://127.0.0.1:8000/api/tags | jq -r '.models[]?.name' 2>/dev/null || echo "  (jq not available)"

echo ""
echo "🌐 Starting Node.js proxy server on port 3000..."
node server.js
