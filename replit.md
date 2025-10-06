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
- **Development Server**: Running on 0.0.0.0:5000
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
- `/` - Dashboard homepage
- `/upload/` - Document upload interface  
- `/admin/` - Django admin interface

## OCR Architecture

### Sistema Híbrido Tesseract + Ollama Vision
O sistema usa uma abordagem híbrida para extração de dados de documentos:

1. **Tesseract OCR** (Primário, Rápido):
   - Extração inicial de texto e QR codes
   - Parse estruturado de documentos portugueses
   - Sistema de scoring de confiança (0-100%)

2. **Ollama Vision** (Fallback Inteligente, Robusto):
   - Ativa automaticamente quando confiança Tesseract < 60%
   - Modelo LLaVA analisa imagem diretamente
   - Prompt instruído para formato JSON estruturado
   - Preserva QR codes detectados pelo Tesseract
   - **Configuração**: Define `OLLAMA_API_URL` para ativar (ex: `http://localhost:11434`)

3. **Normalização de Dados**:
   - Schema garantido para ambos os métodos
   - Conversão segura de tipos numéricos
   - Suporte a formatos europeus e americanos
   - **Limitação conhecida**: Números amb\u00edguos como "2.333" (pode ser 2.333 ou 2333) são interpretados como milhares PT quando têm 3 dígitos após ponto e valor antes entre 1-999. Para precisão total, configure locale ou use Ollama que segue instruções de formatação.

4. **Metadados de Extração**:
   - `_extraction_method`: "tesseract" ou "ollama_vision"
   - `_confidence_score`: 0-100%
   - Salvos em extracao.json e banco de dados

## Recent Changes

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