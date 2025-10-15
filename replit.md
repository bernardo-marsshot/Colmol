# COLMOL - Django Project Setup

## Overview
COLMOL is a Django prototype for intelligent document receipt processing. Its main purpose is to automate document matching between Purchase Orders (PO) and delivery receipts/invoices using OCR simulation, SKU mapping, quantity validation, and digital certification. The project aims to streamline the processing of diverse document formats, manage exceptions gracefully, and provide a comprehensive dashboard for real-time statistics and catalog management.

## User Preferences
I prefer iterative development with clear, concise explanations for any changes or new features. Please ensure that all new functionalities integrate seamlessly with existing systems without breaking current operations. Prioritize robust error handling and fallback mechanisms. I also prefer descriptive and expressive variable names.

## System Architecture
The project is built on Django 5.0.6 using Python 3.11, with SQLite for the database. The frontend utilizes Django templates with HTML/CSS. The system employs a multi-engine OCR approach, primarily using PaddleOCR for its accuracy in Portuguese text and table extraction, with Tesseract OCR as a robust local fallback mechanism.

Key architectural decisions and features include:
-   **Multi-format Document Processing**: Auto-detection and parsing for various document types, including Elastron invoices, Colmol delivery notes, generic documents, and specific Spanish (PEDIDO_ESPANHOL) and French (BON_COMMANDE) purchase order formats. The system now also automatically registers new suppliers from document NIF and unmapped SKUs in purchase orders.
-   **OCR Integration**: Local, offline OCR processing using PaddleOCR (primary) and Tesseract (fallback) for enhanced accuracy and reliability, including QR code detection. A hybrid strategy using OCR for text extraction followed by Groq LLM (Llama-3.3-70B) for intelligent structuring is implemented, with fallbacks to direct OCR data if LLM is unavailable.
-   **Format-Specific and Generic Parsers**: Dedicated parsing logic for known supplier formats and a flexible generic parser with heuristics for unknown formats.
-   **Purchase Order Matching & Validation**: SKU mapping, quantity validation, and exception management for parsing errors and mismatches. Intelligent PO matching for delivery receipts now identifies the correct PO based on supplier and products even without an explicit PO number, using a scoring system.
-   **Bidirectional Document Flow**: Automatic Purchase Order creation from "Notas de Encomenda" and linking with "Guias de Remessa" for comprehensive tracking.
-   **Advanced Illegible File Detection**: Multi-layer validation system to detect and report illegible or malformed documents, automatically creating exception tasks.
-   **User Interface**: Dashboard for KPIs, document filtering, and an admin interface for catalog management. Excel export now includes intelligent dimension extraction from product descriptions as a fallback.
-   **Deployment**: Configured for autoscale deployment.

## External Dependencies
-   **OCR Engines** (4-Level Cascade):
    -   **OCR.space API (Level 0)**: Cloud OCR
    -   **PaddleOCR (Level 1)**: Primary local engine
    -   **EasyOCR (Level 2)**: Secondary local fallback
    -   **Tesseract OCR (Level 3)**: Final local fallback
-   **Groq LLM**: Llama-3.3-70B for intelligent document structuring.
-   **Universal Extraction Tools**:
    -   **Camelot-py**: PDF table extraction
    -   **pdfplumber**: Advanced PDF parsing and table detection
    -   **rapidfuzz**: Fuzzy string matching for multi-language field detection
-   **Database**: SQLite (db.sqlite3).