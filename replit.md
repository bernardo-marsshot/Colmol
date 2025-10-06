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

## Recent Changes

### October 6, 2025
- **Fixed CodeMapping lookup bug**: System was using supplier_code from order reference (e.g., "1ECWH") instead of article_code (product SKU) for lookups, causing all lines to map to the same first result
- **Improved validation logic**: Now uses `article_code` field for CodeMapping queries in both `map_supplier_codes()` and validation
- **Enhanced exception messages**: Changed to show only article_code (e.g., "E0748001901") instead of article_code + supplier_code
- **Quantity validation fix**: Added None-safety with `qty_ordered or 0` and removed conditional check - now always validates quantity even when qty_ordered=0
- **Database schema updates**: Added `article_code` field to ReceiptLine model, added `qty_ordered` field to CodeMapping model
- **Dashboard interactive filter**: Added clickable chart on dashboard to filter documents by status (Processado, Com exceções, Erro, Pendente)
- **Fixed status bug**: Corrected 'exception' to 'exceptions' throughout codebase to match MatchResult model definition

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