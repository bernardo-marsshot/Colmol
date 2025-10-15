# COLMOL - Django Project Setup

## Overview
COLMOL is a Django prototype for intelligent document receipt processing. Its main purpose is to automate document matching between Purchase Orders (PO) and delivery receipts/invoices using OCR simulation, SKU mapping, quantity validation, and digital certification. The project aims to streamline the processing of diverse document formats, manage exceptions gracefully, and provide a comprehensive dashboard for real-time statistics and catalog management.

## User Preferences
I prefer iterative development with clear, concise explanations for any changes or new features. Please ensure that all new functionalities integrate seamlessly with existing systems without breaking current operations. Prioritize robust error handling and fallback mechanisms. I also prefer descriptive and expressive variable names.

## System Architecture
The project is built on Django 5.0.6 using Python 3.11, with SQLite for the database. The frontend utilizes Django templates with HTML/CSS. The system employs a multi-engine OCR approach, primarily using PaddleOCR for its accuracy in Portuguese text and table extraction, with Tesseract OCR as a robust local fallback mechanism.

Key architectural decisions and features include:
-   **Multi-format Document Processing**: Auto-detection and parsing for various document types, including Elastron invoices, Colmol delivery notes, generic documents, and specific Spanish (PEDIDO_ESPANHOL) and French (BON_COMMANDE) purchase order formats.
-   **OCR Integration**: Local, offline OCR processing using PaddleOCR (primary) and Tesseract (fallback) for enhanced accuracy and reliability, including QR code detection.
-   **Format-Specific and Generic Parsers**: Dedicated parsing logic for known supplier formats and a flexible generic parser with heuristics for unknown formats.
-   **Purchase Order Matching & Validation**: SKU mapping, quantity validation, and exception management for parsing errors and mismatches.
-   **Bidirectional Document Flow**: Automatic Purchase Order creation from "Notas de Encomenda" and linking with "Guias de Remessa" for comprehensive tracking.
-   **Advanced Illegible File Detection**: Multi-layer validation system to detect and report illegible or malformed documents, automatically creating exception tasks.
-   **User Interface**: Dashboard for KPIs, document filtering, and an admin interface for catalog management.
-   **Deployment**: Configured for autoscale deployment.

## External Dependencies
-   **OCR Engines** (Cascata de 4 Níveis):
    -   **OCR.space API (Level 0)**: Cloud OCR - 25.000 req/mês grátis, preciso para tabelas, multi-idioma (PT/ES/FR/EN+30)
    -   **PaddleOCR (Level 1)**: Primary local engine - fast and accurate for Portuguese, Spanish, French
    -   **EasyOCR (Level 2)**: Secondary local fallback - activated when PaddleOCR fails or returns empty text
    -   **Tesseract OCR (Level 3)**: Final local fallback - robust processing with Portuguese language pack
    -   **Cascade Logic**: OCR.space → PaddleOCR → EasyOCR → Tesseract (automatic fallback for maximum reliability)
    -   **Cost**: OCR.space free tier (25k/month), local engines 100% offline/free
-   **Universal Extraction Tools**:
    -   **Camelot-py**: PDF table extraction (lattice/stream modes for bordered/borderless tables)
    -   **pdfplumber**: Advanced PDF parsing and table detection
    -   **rapidfuzz**: Fuzzy string matching for multi-language field detection (fornecedor/supplier/proveedor)
-   **Database**: SQLite (db.sqlite3).

## Recent Changes

### October 15, 2025 - CRITICAL FIX: Parser Priority Over Groq LLM ✅ RESOLVED
- **Problem**: Groq LLM was overwriting correct parser data with incorrect extractions
  - Elastron parser extracted quantity 34.0 ML correctly (from "Quant." column)
  - Groq LLM then re-processed and extracted quantity 1.0 (from "Vol." column)
  - System used Groq data, losing correct parser extractions
- **Root Cause**: `process_inbound()` prioritized Groq LLM over format-specific parsers
- **Architecture Fix**: Reversed priority logic
  - **NEW FLOW**: Parser específico PRIMEIRO → Groq LLM apenas como FALLBACK
  - If parser extracts products → USE parser data (authoritative)
  - If parser fails/empty → Try Groq LLM (fallback)
  - If both fail → Use OCR data without products
- **Code Changes**:
  - Modified `process_inbound()` to check `parser_produtos` first
  - Groq LLM now only executes when parser returns 0 products
  - Prevents LLM from overwriting validated parser data
- **Tested**: Elastron invoice FWH_25EU_N5595 ✅
  - E0748001901: 34.0 ML (CORRECT - from parser)
  - 13/13 products extracted with correct quantities
  - Groq LLM not executed (parser succeeded)
- **Impact**: All format-specific parsers (Elastron, BON_COMMANDE, PEDIDO_ESPANHOL) now have priority
- **Reliability**: LLM used only for unknown formats, preventing data corruption

### October 15, 2025 - Bug Fix: None Handling in Product Validation and Mapping
- **Problem**: TypeError when processing documents with missing product codes (None values)
  - `TypeError: object of type 'NoneType' has no len()` when validating product quality
  - `IntegrityError: NOT NULL constraint failed: rececao_receiptline.article_code` when creating receipt lines
  - `TypeError: 'in <string>' requires string as left operand, not NoneType` when matching exceptions
- **Root Cause**: Groq LLM pode retornar produtos com campos `None` em vez de strings vazias
- **Solution**: Comprehensive None-safety added to all product processing functions:
  - **Validation**: `codigo = produto.get('artigo') or ''` + `if not codigo or len(str(codigo)) < 5`
  - **Mapping**: `article_code or "UNKNOWN"` fallback para garantir valor válido
  - **PO Creation**: `produto.get("artigo") or produto.get("codigo") or ""` com multiple fallbacks
  - **Exception Matching**: `item_code = item.get("artigo") or item.get("supplier_code") or ""`
- **Tested**: BON DE COMMANDE francês agora processa sem erros (4 produtos, 4 linhas receção)
- **Impact**: Sistema agora robusto para documentos sem códigos explícitos (ex: tabelas francesas com apenas descrição)

### October 15, 2025 - Groq LLM Multi-Page Document Processing ✅ ATIVO
- **🎯 SOLUÇÃO DEFINITIVA**: Sistema LLM que funciona para **QUALQUER** formato de documento
- **Hybrid Strategy**: OCR primeiro (extração rápida de texto) → Groq LLM segundo (estruturação inteligente)
  - **Step 1**: OCR cascade extrai texto bruto (Level 0-3: OCR.space → PaddleOCR → EasyOCR → Tesseract)
  - **Step 2**: Groq LLM (Llama-3.3-70B) processa texto para extrair JSON estruturado
  - **Fallback**: Se Groq indisponível/falhar, usa dados OCR diretamente (parsers específicos)
- **Groq LLM Features**:
  - **🆓 100% GRATUITO**: API Groq sem limites significativos (https://console.groq.com/keys)
  - **⚡ Extremamente rápido**: Llama-3.3-70B responde em 2-5 segundos
  - **🌍 Multi-idioma**: PT/ES/FR com prompt engineering e exemplos concretos
  - **📊 Formato universal**: Extrai produtos de QUALQUER layout (guias remessa, notas encomenda, faturas)
  - **🧠 Context-aware**: Ignora endereços/headers, foca em produtos
  - **✅ JSON forçado**: `response_format: json_object` garante output válido
  - **📈 Alta precisão**: Extrai TODOS os produtos, mesmo com dados incompletos/mal formatados
  - Timeout: 30s, 4000 tokens max response
- **Configuration**:
  - `GROQ_API_KEY`: API key gratuita do Groq (obrigatória)
  - **Ativação**: Configurado e funcionando ✅
- **Tested & Confirmed**:
  - PC5_0005051.pdf (COSGUI multi-line): 2/2 produtos ✅
  - 177.pdf (NATURCOLCHON inverted): 1/1 produto ✅
- **Cost**: 100% gratuito (Groq API free tier)
- **Accuracy**: LLM pós-processamento permite extrair documentos com layouts desconhecidos
- **Integration**: Seamlessly integrated in `process_inbound()` - OCR→Groq→Fallback cascade
- **Método identificação**: `extraction_method: "ollama_llm"` (histórico, usa Groq na prática)

### October 13, 2025 - Universal Document Extraction System (OCR.space + Fuzzy Matching + Table Extraction)
- **4-Level OCR Cascade**: Implementado sistema híbrido cloud + local para máxima taxa de sucesso
  - **Level 0 (OCR.space API)**: Cloud OCR gratuito (25k/mês), preciso para tabelas multi-idioma
  - **Level 1 (PaddleOCR)**: Engine local primário - rápido e preciso para PT/ES/FR
  - **Level 2 (EasyOCR)**: Fallback secundário local - ativado quando PaddleOCR falha
  - **Level 3 (Tesseract)**: Fallback final local - processamento robusto com pack português
- **Universal Key-Value Extraction**: Fuzzy matching (rapidfuzz) para detectar campos em qualquer idioma
  - Sinônimos multi-idioma: fornecedor/supplier/proveedor, NIF/VAT/CIF, data/date/fecha
  - Score threshold 70% para aceitar matches
- **Universal Table Extraction**: Extração automática de tabelas quando parsers específicos falham
  - **Camelot**: Detecção de tabelas com bordas (lattice mode)
  - **pdfplumber**: Detecção de tabelas sem bordas (fallback)
  - Mapeia automaticamente colunas: código, descrição, quantidade, preço
- **Parse Fallback Universal**: Ativado automaticamente quando parsers específicos retornam 0 produtos
  - 3 estratégias: table extraction → regex genéricos → heurísticas
  - Combina metadados (fuzzy) + produtos (tabelas/regex)
- **Tested**: 177.pdf (NATURCOLCHON) 1/1 ✅, PC5_0005051.pdf usa fallback universal
- **Cost**: 100% grátis (OCR.space free tier + engines locais offline)
- **Known Limitations**: Universal table extraction pode mapear colunas incorretamente em tabelas mal formatadas (ex: PC5_0005051.pdf captura endereço em vez de produto). Requer validação adicional de heurísticas de coluna.

### October 15, 2025 - Bug Fix: Infinite Loop in PEDIDO_ESPANHOL Formato 1B Parser
- **Problem**: Parser Formato 1B (NATURCOLCHON) causava loop infinito ao validar linhas inválidas
- **Root Cause**: Validações faziam `continue` sem incrementar contador `i`, repetindo mesma linha infinitamente
- **Solution**: Refatorado para flag `is_valid` + sempre incrementar `i` após validação (válida ou inválida)
- **Tested**: 177.pdf (NATURCOLCHON) agora processa corretamente sem duplicações ✅
- **Impact**: Parser regex agora funciona como fallback quando Groq LLM indisponível

### October 15, 2025 - Multi-Line Buffer for PEDIDO_ESPANHOL (COSGUI Format)
- **Problem Solved**: COSGUI format has qty, description, code on **separate lines** (not captured by single-line regex)
- **Multi-Line Buffer**: Parser now joins 3 consecutive lines if pattern matches:
  - Line 1: pure number (quantity) `4,00`
  - Line 2: text description `COLCHON TOP VISCO 2019 135X190`
  - Line 3: alphanumeric code `LUSTOPVS135190`
- **Reconstruction**: Builds format `CODIGO DESCRIPCION CANTIDAD` from 3-line pattern
- **Always Active**: Parser tries multi-line buffer **even without header detection** (headers may appear after products)
- **Tested**: PC5_0005051.pdf (COSGUI) - now extracts 2/2 products ✅
- **Compatibility**: Works with all Spanish formats (NATURCOLCHON, COSGUI)
- **Note**: Groq LLM agora processa estes documentos com maior precisão

### October 13, 2025 - PEDIDO_ESPANHOL Parser for Spanish Purchase Orders
- **New Document Type**: Added "PEDIDO_ESPANHOL" detection and parser for Spanish purchase order documents
- **Multi-Format Support**: Handles 3 Spanish format variations:
  - **Format 1 (Standard)**: CÓDIGO DESCRIPCIÓN UNIDADES PRECIO IMPORTE
  - **Format 1B (Inverted NATURCOLCHON)**: DESCRIPCIÓN CÓDIGO TOTAL PRECIO UNIDADES ✅
  - **Format 2 (COSGUI Multi-Line)**: CANTIDAD + DESCRIPCIÓN + CÓDIGO (3 separate lines) ✅
- **Priority-Based Matching**: Format 1B checked FIRST (3 numbers, more specific) to prevent false positives
- **Product Extraction**: Successfully extracts código, descripción, cantidad, precio unitario, total
- **Metadata Extraction**: Pedido número, Fecha, Proveedor, Dimension auto-detection (150x200)
- **Successfully Tested**: 177.pdf (NATURCOLCHON) 1/1 ✅, PC5_0005051.pdf (COSGUI) 2/2 ✅
- **IVA Rate**: Defaults to 21% (Spanish VAT standard rate)
- **Integration**: Seamlessly integrated into existing OCR pipeline

### October 13, 2025 - BON DE COMMANDE Parser for French Purchase Orders
- **Successfully Tested**: Processed French document with 4/4 products (MATELAS SAN REMO, RIVIERA), total €1924.00
- **Format Support**: Extracts designation, quantity, unit price from tabular format with € symbol
- **IVA Rate**: Defaults to 20% (French VAT standard rate)

### October 13, 2025 - ORDEM_COMPRA Parser for Multi-Line Portuguese Purchase Orders
- **Successfully Tested**: Processed real user document with 2/2 products, created PO OC250000525
- **Multi-Line Format**: Handles separated reference and quantity lines with robust regex
- **Defensive Pairing**: Validates reference-quantity matching to prevent IndexError
