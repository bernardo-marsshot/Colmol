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
- **Multi-format Document Processing**: Auto-detection and parsing for various document types (e.g., Elastron invoices, Colmol delivery notes, generic documents, specific Spanish/French PO formats).
- **OCR Integration**: A 5-level cascade OCR system (PyMuPDF → PyPDF2 → OCR.space → PaddleOCR/EasyOCR → Tesseract) with intelligent fallback ensures maximum success rates, supporting multi-page processing, local offline processing, and QR code detection. OCR data is prioritized over LLM data if products are extracted.
- **LLM Integration**: Groq LLM (Llama-3.3-70B) is used for universal document extraction and structuring, processing OCR-extracted text into structured JSON, acting as a fallback when OCR extracts zero products.
- **Format-Specific and Generic Parsers**: Dedicated parsing logic for known supplier formats and a flexible generic parser for unknown formats, including robust product validation and number normalization.
- **Purchase Order Matching & Validation**: SKU mapping, quantity validation, exception management, and a decremental matching system. Includes bidirectional document flow, multi-PO handling, and line-item matching for delivery receipts with multiple POs.
- **Advanced Illegible File Detection**: Multi-layer validation system detects and reports illegible documents, creating exception tasks.
- **Excel Export Enhancements**: Intelligent dimension extraction and "Mini Códigos FPOL" mapping for standardized Excel exports.
- **Robustness**: Comprehensive None-safety across product processing functions, automatic creation of `CodeMapping` for unknown products, and flexible product validation allowing acceptance based on description and quantity.
- **Differentiated Status**: Clear distinction between 'Error' (critical processing failures) and 'Exceptions' (business logic problems).

**System Design Choices:**
- Configured for autoscale deployment.
- Emphasizes robust error handling and fallback mechanisms for OCR and LLM integrations.
- Universal number normalization based on digit count after the comma (3 digits = thousands separator, 1-2 digits = decimal).

## External Dependencies
-   **OCR Engines**:
    -   **PyMuPDF (fitz)**: Level 1 - Fast multi-page PDF extraction.
    -   **PyPDF2**: Level 2 - Embedded text extraction fallback.
    -   **OCR.space API**: Level 3 - Cloud OCR.
    -   **PaddleOCR**: Level 4 - Primary local engine.
    -   **EasyOCR**: Level 4 - Secondary local fallback.
    -   **Tesseract OCR**: Level 4 - Final local fallback (with Portuguese).
-   **Large Language Model**:
    -   **Groq API**: Utilizes Llama-3.3-70B.
    -   **Ollama**: Final LLM fallback.
-   **Universal Extraction Tools**:
    -   **Camelot-py**: PDF table extraction.
    -   **pdfplumber**: Advanced PDF parsing.
    -   **rapidfuzz**: Fuzzy string matching.
-   **Database**: SQLite (db.sqlite3).