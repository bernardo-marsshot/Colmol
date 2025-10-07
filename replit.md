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

### October 7, 2025 - Tesseract OCR Migration
- **Simplified to Tesseract Only**: Removed OCR.space dependency, now using only local Tesseract OCR
- **Improved Elastron Parser**: Adapted for Tesseract output format - now extracts 13/13 products (100%)
- **Fixed Colmol Parser**: Corrected dimension pattern detection - now extracts 7/7 products (100%)
- **Tesseract-Compatible Parsing**: Modified parsers to work with Tesseract's spaced text format
- **Format-Specific Parsers**: 
  - `parse_fatura_elastron()`: Handles Elastron invoices with Tesseract format (100% extraction rate)
  - `parse_guia_colmol()`: Processes Colmol delivery notes with encomenda/requisição tracking (100% extraction rate)
  - Generic fallback for unknown formats
- **Multi-Format Support**: Successfully tested with:
  - Elastron invoices (13/13 products extracted)
  - Colmol delivery notes (7/7 products extracted)
- **Offline Processing**: No external API dependencies, fully local OCR processing

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

### Tesseract OCR
- **Engine**: Tesseract OCR (local, offline processing)
- **Language**: Portuguese (`por`) language pack
- **Features**: Text extraction, QR code detection (OpenCV), table parsing
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