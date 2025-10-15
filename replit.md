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

### October 15, 2025 - Ollama LLM Integration (Hybrid OCR + LLM Post-Processing)
- **Hybrid Strategy**: OCR first (fast text extraction) → Ollama LLM second (intelligent structuring)
  - **Step 1**: OCR cascade extracts raw text (Level 0-3: OCR.space → PaddleOCR → EasyOCR → Tesseract)
  - **Step 2**: Ollama LLM processes text + vision to extract structured JSON
  - **Fallback**: If Ollama unavailable/fails, uses OCR data directly
- **Ollama Features**:
  - Multi-language support (PT/ES/FR) via prompt engineering
  - JSON-forced output with schema validation
  - Vision model support (converts PDF to image for visual analysis)
  - Intelligent product extraction from tables (even malformed ones)
  - Timeout: 60s (slower than OCR but more accurate)
- **Configuration**:
  - `OLLAMA_API_URL`: Ollama server endpoint (required)
  - `OLLAMA_MODEL`: Model name (default: llama3.2-vision)
- **Cost**: Free (uses local/remote Ollama without API keys)
- **Accuracy**: LLM post-processing significantly improves extraction for complex/malformed documents
- **Integration**: Seamlessly integrated in `process_inbound()` - OCR+LLM hybrid approach

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

### October 13, 2025 - PEDIDO_ESPANHOL Parser for Spanish Purchase Orders
- **New Document Type**: Added "PEDIDO_ESPANHOL" detection and parser for Spanish purchase order documents
- **Multi-Format Support**: Handles 2 Spanish format variations:
  - **Format 1 (Standard)**: CÓDIGO DESCRIPCIÓN UNIDADES PRECIO IMPORTE
  - **Format 1B (Inverted NATURCOLCHON)**: DESCRIPCIÓN CÓDIGO TOTAL PRECIO UNIDADES ✅
  - **Format 2 (Simple)**: CÓDIGO DESCRIPCIÓN CANTIDAD (partial - needs multi-line buffer)
- **Priority-Based Matching**: Format 1B checked FIRST (3 numbers, more specific) to prevent false positives
- **Product Extraction**: Successfully extracts código, descripción, cantidad, precio unitario, total from NATURCOLCHON format
- **Metadata Extraction**: Pedido número, Fecha, Proveedor, Dimension auto-detection (150x200)
- **Successfully Tested**: 177.pdf (NATURCOLCHON) - 1/1 products extracted ✅
- **Pending Format**: PC5_0005051.pdf (COSGUI) - requires multi-line buffer (qty, desc, code on separate lines)
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
