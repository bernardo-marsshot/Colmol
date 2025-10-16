# COLMOL - Django Project Setup

## Overview
COLMOL is a Django prototype for intelligent document receipt processing. Its main purpose is to automate document matching between Purchase Orders (PO) and delivery receipts/invoices using OCR simulation, SKU mapping, quantity validation, and digital certification. The project aims to streamline the processing of diverse document formats, manage exceptions gracefully, and provide a comprehensive dashboard for real-time statistics and catalog management. The business vision is to transform complex, manual document processing into an efficient, automated workflow, significantly reducing operational costs and improving data accuracy.

## User Preferences
I prefer iterative development with clear, concise explanations for any changes or new features. Please ensure that all new functionalities integrate seamlessly with existing systems without breaking current operations. Prioritize robust error handling and fallback mechanisms. I also prefer descriptive and expressive variable names.

## System Architecture
The project is built on Django 5.0.6 using Python 3.11, with SQLite for the database. The frontend utilizes Django templates with HTML/CSS. The system employs a multi-engine OCR approach for high accuracy and includes LLM integration for universal document extraction.

**UI/UX Decisions:**
- A dashboard provides KPIs and document filtering.
- An admin interface is available for catalog management.

**Technical Implementations & Feature Specifications:**
- **Multi-format Document Processing**: Auto-detection and parsing for various document types (Elastron invoices, Colmol delivery notes, generic, specific Spanish/French PO formats).
- **OCR Integration**: A 4-level cascade OCR system (OCR.space → PaddleOCR → EasyOCR → Tesseract) for maximum success rates, supporting local, offline processing and QR code detection. Includes progressive retry for multi-page PDFs and content quality detection for intelligent OCR fallback.
- **LLM Integration**: Groq LLM (Llama-3.3-70B) for universal document extraction and structuring into JSON.
- **Format-Specific and Generic Parsers**: Dedicated parsing for known supplier formats and a flexible generic parser for unknown formats.
- **Purchase Order Matching & Validation**: SKU mapping, quantity validation, and exception management for parsing errors and mismatches. Supports decremental matching, and individual line-item PO matching for documents with multiple POs.
- **Bidirectional Document Flow**: Automatic PO creation from "Notas de Encomenda" and linking with "Guias de Remessa".
- **Advanced Illegible File Detection**: Multi-layer validation to detect and report illegible or malformed documents.
- **Excel Export Enhancements**: Intelligent dimension extraction and "Mini Códigos FPOL" mapping for standardized exports.
- **Robustness**: Comprehensive None-safety and automatic creation of `CodeMapping` for unknown products.
- **Number Normalization**: Universal system for normalizing numbers based on digit count after the comma.
- **LLM Fallback System**: Automatic fallback to a secondary Groq API key and then to Ollama if primary Groq calls fail.
- **Dashboard Enhancements**: Displays all document types (FT + GR) with clear visual differentiation and distinct status logic for 'Error' (critical OCR/processing failure) vs. 'Exceptions' (business logic issues like mismatches).
- **Multi-PO Handling**: Documents with multiple purchase orders per document create separate POs, with quantity aggregation for duplicate products across POs. PO linking occurs before exception generation.

**System Design Choices:**
- Configured for autoscale deployment.
- Emphasizes robust error handling and fallback mechanisms for OCR and LLM integrations.

## External Dependencies
-   **OCR Engines**:
    -   **OCR.space API**: Cloud OCR.
    -   **PaddleOCR**: Primary local engine.
    -   **EasyOCR**: Secondary local fallback.
    -   **Tesseract OCR**: Final local fallback.
-   **Large Language Model**:
    -   **Groq API**: Llama-3.3-70B.
    -   **Ollama**: Final LLM fallback.
-   **Universal Extraction Tools**:
    -   **Camelot-py**: PDF table extraction.
    -   **pdfplumber**: Advanced PDF parsing.
    -   **rapidfuzz**: Fuzzy string matching.
-   **Database**: SQLite (db.sqlite3).