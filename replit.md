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
- **OCR Engine**: Tesseract OCR (local, offline)
- **Document Formats**: Auto-detection for Elastron invoices, Colmol delivery notes, generic Portuguese documents
- **Demo Data**: Pre-loaded using management command

## Current Configuration
- **Development Server**: Running on 0.0.0.0:5000
- **Host Settings**: ALLOWED_HOSTS = ["*"] (configured for Replit proxy)
- **Static Files**: /static/ directory created
- **Media Files**: /media/ directory for file uploads
- **Deployment**: Configured for autoscale deployment

## Key Features
- **Multi-format Document Processing**: Auto-detects and parses Elastron invoices, Colmol delivery notes, and generic documents
- **Tesseract OCR**: Local offline OCR processing for Portuguese documents
- **Format-Specific Parsers**: Dedicated extraction logic for each supplier format
- **QR Code Detection**: Reads and parses Portuguese fiscal QR codes (AT format)
- **Purchase Order Matching**: SKU mapping and quantity validation
- **Exception Management**: Handles parsing errors and mismatches gracefully
- **Dashboard with KPIs**: Real-time statistics and document filtering
- **Admin Interface**: Catalog management and configuration

## URLs
- `/` - Dashboard homepage
- `/upload/` - Document upload interface  
- `/admin/` - Django admin interface

## Recent Changes

### October 13, 2025 - Bidirectional Nota de Encomenda ↔ Guia de Remessa System
- **Automatic PO Creation from Notas**: Notas de Encomenda (FT) now automatically create PurchaseOrder + POLines from OCR data
- **Smart Document Routing**: process_inbound() detects doc_type='FT' and creates PO instead of matching logic
- **Bidirectional Linking**: InboundDocument.po field with related_name='inbound_docs' enables access to linked Guias from PO
- **Page Separation**: 
  - **Dashboard**: Shows ONLY Guias de Remessa (GR) - filters out Notas de Encomenda
  - **Encomendas Page**: Shows PurchaseOrders created from Notas + linked Guias with status badges
- **Enhanced Encomendas Page**: po_list.html displays all Guias received for each PO with clickable links and status badges (✓ matched, ! exceptions)
- **Dashboard PO Links**: Dashboard shows clickable PO links (📋) for each Guia with link to Encomendas page
- **Nomenclature Updates**: 
  - Navigation: "Carregar Guia/Fatura" → "Carregar Documento"
  - Doc types: "Fatura" → "Nota de Encomenda", "Guia de Remessa" maintained
- **Template Safety**: po_list.html now guards against missing MatchResult to prevent crashes
- **Complete Flow**: Nota de Encomenda → creates PO (visible in Encomendas) → Guia de Remessa → matches with PO → visible in both pages

### October 9, 2025 - PaddleOCR Integration with Tesseract Fallback
- **PaddleOCR as Primary Engine**: Upgraded from Tesseract-only to PaddleOCR as primary OCR engine (30% more accurate for Portuguese text, better table extraction)
- **Lazy Loading Implementation**: Created `get_paddle_ocr()` function with lazy initialization to avoid Django startup errors with system dependencies (libgomp.so.1)
- **Complete Fallback Mechanism**: Automatic fallback PaddleOCR → Tesseract with per-page error handling:
  - If PaddleOCR import fails → uses Tesseract for all documents
  - If PaddleOCR.ocr() throws exception → catches error and retries with Tesseract
  - If PaddleOCR returns empty/low-confidence text → automatically tries Tesseract
  - Informative logging when fallback occurs
- **Per-Page Processing**: Both PDF and image OCR functions handle failures gracefully on a per-page basis
- **No External Dependencies**: Both PaddleOCR and Tesseract are local/offline, completely free, no API keys required
- **Maintained Compatibility**: All existing parsers (Elastron 13/13, Colmol 7/7, Generic) continue working with improved accuracy

### October 7, 2025 - Tesseract OCR Migration, Generic Parser & Advanced Validation
- **Simplified to Tesseract Only**: Removed OCR.space dependency, now using only local Tesseract OCR
- **Improved Elastron Parser**: Adapted for Tesseract output format - now extracts 13/13 products (100%)
- **Fixed Colmol Parser**: Corrected dimension pattern detection - now extracts 7/7 products (100%)
- **Tesseract-Compatible Parsing**: Modified parsers to work with Tesseract's spaced text format
- **Generic Parser for Any Supplier**: Created `parse_guia_generica()` with flexible heuristics to extract products from ANY delivery note format
  - Detects product codes (8+ alphanumeric chars), descriptions, quantities, and units
  - Supports PT (25,000) and EN (25.0) number formats
  - Extracts dimensions from descriptions (1980x0880x0020 → 1.98x0.88x0.02)
  - Automatic fallback: if specific parser fails, tries generic parser
- **Advanced Illegible File Detection**: Multi-layer validation system with automatic ExceptionTask creation:
  1. **Text length validation**: Text < 100 chars → "Ficheiro ilegível - texto muito curto"
  2. **Product extraction validation**: Guia/Fatura with 0 products → "Ficheiro ilegível - nenhum produto extraído"
  3. **Low quality detection**: pdfplumber text < 50 chars + no products → "Ficheiro ilegível - qualidade de imagem muito baixa"
  4. **Product quality validation**: >50% invalid products (code <5 chars OR quantity ≤0) → "Ficheiro desformatado - X/Y produtos com dados inválidos"
- **OCR Performance & Timeout Protection**:
  - **DPI optimized**: Reduced from 300 to 200 DPI for faster processing with acceptable quality
  - **Per-page timeout**: 15-second timeout per page prevents hanging on low-quality images
  - **Graceful degradation**: Skips timed-out pages and continues processing
  - **Performance tracking**: Logs conversion time and per-page processing time
  - **Timeout handling**: Automatically detects and reports OCR timeout errors
- **Format-Specific Parsers**: 
  - `parse_fatura_elastron()`: Handles Elastron invoices with Tesseract format (100% extraction rate)
  - `parse_guia_colmol()`: Processes Colmol delivery notes with encomenda/requisição tracking (100% extraction rate)
  - `parse_guia_generica()`: Universal parser for any supplier's delivery notes with fallback support
- **Multi-Format Support**: Successfully tested with:
  - Elastron invoices (13/13 products extracted)
  - Colmol delivery notes (7/7 products extracted)
  - Generic delivery notes from multiple suppliers
  - Malformed/low-quality PDFs (automatic exception creation)
- **Offline Processing**: No external API dependencies, fully local OCR processing
- **Excel Export Fix**: Updated `export_document_to_excel()` to handle dimensions as strings (Tesseract format) instead of dictionaries

### October 6, 2025
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

## OCR Configuration

### PaddleOCR (Primary Engine)
- **Engine**: PaddleOCR (local, offline processing, 30% more accurate than Tesseract)
- **Language**: Multilingual model with excellent Portuguese support
- **Features**: Advanced text extraction, better table detection, confidence scoring
- **Lazy Loading**: Initialized only when needed to avoid startup issues
- **Automatic Fallback**: Falls back to Tesseract if unavailable or fails

### Tesseract OCR (Fallback Engine)
- **Engine**: Tesseract OCR (local, offline processing)
- **Language**: Portuguese (`por`) language pack
- **Features**: Text extraction, QR code detection (OpenCV), table parsing
- **Usage**: Automatic fallback when PaddleOCR fails or returns empty results
- **No API Keys Required**: Fully local processing without external dependencies

### Supported Document Formats
1. **Fatura Elastron**: Auto-detected via "elastron" + "fatura" keywords (100% extraction rate)
2. **Guia Colmol**: Auto-detected via "colmol" + "guia" keywords (100% extraction rate)
3. **Generic Invoices**: Fallback parser for unknown invoice formats
4. **Generic Delivery Notes**: Fallback parser for unknown guia formats

## Next Steps
- Add more supplier-specific parsers (expand format library)
- Email IMAP connector for automatic document ingestion
- Mobile PWA for physical verification
- Export capabilities to PHC systems