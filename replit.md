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

## Recent Changes (Sept 24, 2025)
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