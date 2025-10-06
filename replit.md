# COLMOL - Django Project Setup

## Overview
COLMOL is a Django prototype for intelligent document receipt processing. The project implements document matching between Purchase Orders (PO) and delivery receipts/invoices using OCR simulation, SKU mapping, quantity validation, and digital certification.

## Project Status
Successfully imported and configured for Replit environment on September 24, 2025.

## Architecture
- **Framework**: Django 5.0.6
- **Database**: SQLite (db.sqlite3)
- **Language**: Python 3.11
- **Frontend**: Django templates with HTML/CSS
- **Demo Data**: Pre-loaded using management command

## Current Configuration
- **Django Server**: Running on 0.0.0.0:5000 (main application)
- **Ollama Server**: Running on 0.0.0.0:8000 (internal)
- **Node.js Proxy**: Running on 0.0.0.0:3000 (Ollama HTTP proxy with streaming)
- **Host Settings**: ALLOWED_HOSTS = ["*"] (configured for Replit proxy)
- **Static Files**: /static/ directory created
- **Media Files**: /media/ directory for file uploads
- **Deployment**: Configured for autoscale deployment

## Key Features
- Document upload and OCR simulation
- Purchase Order and receipt matching
- SKU mapping and validation
- Exception management
- Dashboard with KPIs
- Admin interface for catalog management

## URLs
- `/` - Dashboard homepage (Django - port 5000)
- `/upload/` - Document upload interface (Django - port 5000)
- `/admin/` - Django admin interface (Django - port 5000)
- `http://localhost:3000/health` - Ollama proxy health check
- `http://localhost:3000/generate` - Ollama proxy API endpoint

## OCR Architecture

### Sistema de Extração Inteligente
O sistema oferece dois métodos de extração configuráveis:

**1. Ollama Vision** (Recomendado - Visão Computacional):
   - **Ativação**: Define `OLLAMA_API_URL` para usar como método primário
   - Modelo LLaVA analisa imagem diretamente sem OCR intermediário
   - Extrai dados estruturados em JSON via prompt otimizado
   - Números sempre normalizados (sem separadores de milhares)
   - Detecta QR codes automaticamente via OpenCV
   - **Configuração**: `OLLAMA_API_URL=http://localhost:8000` (direto) ou `http://localhost:3000` (via proxy)
   - **Modelo**: `OLLAMA_MODEL=llava:latest` (padrão)
   - **Proxy Node.js**: Resolve timeouts de 60s com keepAlive=610s e streaming completo

**2. Tesseract OCR** (Fallback Automático):
   - Ativa quando Ollama não está configurado
   - Extração de texto e QR codes via OCR tradicional
   - Parse estruturado de documentos portugueses
   - Funciona sem configuração adicional

**Normalização de Dados**:
   - Schema garantido para ambos os métodos
   - Conversão segura de tipos numéricos
   - Ollama segue instruções do prompt para formato consistente

**Metadados de Extração**:
   - `_extraction_method`: "tesseract" ou "ollama_vision"
   - `_confidence_score`: 0-100%
   - Salvos em extracao.json e banco de dados
## Recent Changes

### October 6, 2025 (Proxy Node.js para Ollama)
- **Implementado proxy HTTP Express**: Resolve timeouts de 60s no Ollama com keepAliveTimeout=610s e headersTimeout=620s
- **Streaming completo**: SSE/chunked sem buffer, retransmite tokens imediatamente ao cliente
- **Seleção automática de modelos**: Sistema detecta presença de imagem e escolhe entre cheap_text (texto) e vision (multimodal)
- **Upload de imagens via multipart**: Suporta form-data com conversão automática para base64
- **Otimizado para CPU**: OLLAMA_NUM_PARALLEL=1, mmap ativado, batch_size reduzido
- **Arquivos criados**: server.js, start.sh, package.json, models.json
- **Node.js 20 instalado**: Com Express e Busboy para proxy HTTP
- **Workflow integrado**: start.sh gerencia Ollama + Proxy simultaneamente na porta 3000
- **CORS configurado**: Permite localhost e domínios Replit
- **Health check**: Endpoint /health verifica status do Ollama

### October 6, 2025 (Sistema Híbrido)
- **Implementado sistema híbrido Tesseract + Ollama Vision**: OCR robusto com fallback inteligente
- **Sistema de confiança**: Calcula score 0-100% baseado em completude dos dados extraídos
- **Fallback automático**: Ollama Vision ativado quando confiança < 60%
- **Normalização robusta**: Schema garantido, conversão segura de tipos, preservação de QR codes
- **Prompt otimizado**: Ollama instruído para retornar números sem separadores de milhares
- **Logs detalhados**: Rastreamento de método usado, confiança, e comparações

### October 6, 2025 (Correções Anteriores)
- **Fixed CodeMapping lookup bug**: System was using supplier_code from order reference (e.g., "1ECWH") instead of article_code (product SKU) for lookups, causing all lines to map to the same first result
- **Improved validation logic**: Now uses `article_code` field for CodeMapping queries in both `map_supplier_codes()` and validation
- **Enhanced exception messages**: Changed to show only article_code (e.g., "E0748001901") instead of article_code + supplier_code
- **Quantity validation fix**: Added None-safety with `qty_ordered or 0` and removed conditional check - now always validates quantity even when qty_ordered=0
- **Database schema updates**: Added `article_code` field to ReceiptLine model, added `qty_ordered` field to CodeMapping model
- **Dashboard interactive filter**: Added clickable chart on dashboard to filter documents by status (Processado, Com exceções, Erro, Pendente) - uses CSS classes with !important for reliable filtering
- **Fixed status bug**: Corrected 'exception' to 'exceptions' throughout codebase to match MatchResult model definition
- **Filter CSS fix**: Strengthened filter implementation with `.filtered-out` CSS class to ensure hidden elements stay hidden regardless of other styles
- **Modal close fix**: Fixed popup/modal backdrop not closing completely - added JavaScript to remove leftover backdrops and reset body styles
- **Detail page chart**: Added line reading statistics chart to individual document detail pages - shows document-specific breakdown of lines read vs lines with errors
- **Document history**: Removed 10-document limit from dashboard - now shows all documents from beginning with vertical scroll (600px max height) to preserve complete history
- **Excel dimensões fix**: Fixed Excel export to correctly show product dimensions (largura x comprimento x espessura) for Guia de Remessa documents - now matches products using article_code and supports both new (produtos[]) and legacy (lines[]) formats

### September 24, 2025
- Installed Python 3.11 and Django 5.0.6
- Created static and media directories
- Loaded demo data successfully
- Configured workflow for port 5000
- Set up deployment configuration
- Verified all core functionality working

## Next Steps
- Integration with real OCR services (AWS Textract, Google Document AI)
- Email IMAP connector for automatic ingestion
- Mobile PWA for physical verification
- Export capabilities to PHC systems