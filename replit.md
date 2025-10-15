# COLMOL - Django Project Setup

## Overview
COLMOL is a Django prototype for intelligent document receipt processing. Its main purpose is to automate document matching between Purchase Orders (PO) and delivery receipts/invoices using OCR simulation, SKU mapping, quantity validation, and digital certification. The project aims to streamline the processing of diverse document formats, manage exceptions gracefully, and provide a comprehensive dashboard for real-time statistics and catalog management. The business vision is to automate and optimize document processing, offering significant market potential in logistics and supply chain management.

## User Preferences
I prefer iterative development with clear, concise explanations for any changes or new features. Please ensure that all new functionalities integrate seamlessly with existing systems without breaking current operations. Prioritize robust error handling and fallback mechanisms. I also prefer descriptive and expressive variable names.

## System Architecture
The project is built on Django 5.0.6 using Python 3.11, with SQLite for the database. The frontend utilizes Django templates with HTML/CSS. The system employs a multi-engine OCR approach, primarily using PaddleOCR for its accuracy in Portuguese text and table extraction, with Tesseract OCR as a robust local fallback mechanism.

Key architectural decisions and features include:
-   **Multi-format Document Processing**: Auto-detection and parsing for various document types, including Elastron invoices, Colmol delivery notes, generic documents, and specific Spanish (PEDIDO_ESPANHOL) and French (BON_COMMANDE) purchase order formats.
-   **OCR Integration**: Local, offline OCR processing using PaddleOCR (primary) and Tesseract (fallback) for enhanced accuracy and reliability, including QR code detection. A 4-level cascade system integrates cloud (OCR.space) and local OCR engines.
-   **AI-Powered Extraction**: Utilizes Groq LLM (Llama-3.3-70B) for intelligent, multi-language, and format-agnostic extraction of structured JSON from OCR-processed text, with an automatic retry mechanism for rate limits.
-   **Format-Specific and Generic Parsers**: Dedicated parsing logic for known supplier formats and a flexible generic parser with heuristics for unknown formats, including universal key-value extraction using fuzzy matching and table extraction.
-   **Purchase Order Matching & Validation**: SKU mapping, quantity validation, and exception management for parsing errors and mismatches.
-   **Bidirectional Document Flow**: Automatic Purchase Order creation from "Notas de Encomenda" and linking with "Guias de Remessa" for comprehensive tracking.
-   **Advanced Illegible File Detection**: Multi-layer validation system to detect and report illegible or malformed documents, automatically creating exception tasks.
-   **User Interface**: Dashboard for KPIs, document filtering, and an admin interface for catalog management.
-   **Deployment**: Configured for autoscale deployment.
-   **Excel Export**: Exports essential data (Mini Código, Dimensões, Quantidade) with intelligent dimension extraction from product descriptions as a fallback.
-   **Robustness**: Comprehensive None-safety implemented across product processing functions to handle missing data gracefully.

## External Dependencies
-   **OCR Engines (Cascata de 4 Níveis)**:
    -   **OCR.space API**: Cloud OCR (Level 0)
    -   **PaddleOCR**: Primary local engine (Level 1)
    -   **EasyOCR**: Secondary local fallback (Level 2)
    -   **Tesseract OCR**: Final local fallback (Level 3)
-   **LLM**: Groq API (for Llama-3.3-70B)
-   **Universal Extraction Tools**:
    -   **Camelot-py**: PDF table extraction
    -   **pdfplumber**: Advanced PDF parsing and table detection
    -   **rapidfuzz**: Fuzzy string matching
-   **Database**: SQLite (db.sqlite3)