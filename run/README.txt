====================================
COLMOL - Scripts de Execução Local
====================================

Esta pasta contém scripts para rodar o COLMOL localmente no seu computador.

📁 ARQUIVOS DISPONÍVEIS:

1. start.sh (Linux/Mac)
   - Inicia Ollama + Proxy Node.js + Django
   - Uso: bash run/start.sh

2. start.bat (Windows)
   - Inicia Ollama + Proxy Node.js + Django
   - Uso: run\start.bat

3. start-django-only.sh (Linux/Mac)
   - Inicia apenas Django (se Ollama já estiver rodando)
   - Uso: bash run/start-django-only.sh

4. start-django-only.bat (Windows)
   - Inicia apenas Django (se Ollama já estiver rodando)
   - Uso: run\start-django-only.bat

📋 REQUISITOS:

- Python 3.11+
- Node.js 20+
- Ollama (opcional, para OCR com IA)

🚀 COMO USAR:

== LINUX/MAC ==
1. Dar permissão de execução:
   chmod +x run/start.sh run/start-django-only.sh

2. Executar:
   bash run/start.sh

== WINDOWS ==
1. Executar (duplo clique ou via CMD):
   run\start.bat

🔧 PORTAS UTILIZADAS:

- Django:  http://localhost:5000  (interface principal)
- Proxy:   http://localhost:3000  (proxy Ollama)
- Ollama:  http://localhost:8000  (servidor IA)

⚠️  IMPORTANTE:

- Se as portas já estiverem em uso, os scripts vão falhar
- Para parar os servidores: Pressione Ctrl+C
- Ollama demora alguns segundos para iniciar na primeira vez
- O modelo llava:latest (~4.7GB) será baixado automaticamente

📖 DOCUMENTAÇÃO COMPLETA:

Consulte o arquivo replit.md na raiz do projeto para mais detalhes
sobre arquitetura, configuração e troubleshooting.

====================================
Suporte: Consulte logs no terminal
====================================
