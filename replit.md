# COLMOL - Django Project Setup

## Overview
COLMOL is a Django prototype for intelligent document receipt processing. Its main purpose is to automate document matching between Purchase Orders (PO) and delivery receipts/invoices. This is achieved through OCR simulation, SKU mapping, quantity validation, and digital certification. The project aims to streamline the processing of diverse document formats, manage exceptions gracefully, and provide a comprehensive dashboard for real-time statistics and catalog management. The business vision is to enhance efficiency in supply chain management by automating a critical, often manual, process.

## User Preferences
I prefer iterative development with clear, concise explanations for any changes or new features. Please ensure that all new functionalities integrate seamlessly with existing systems without breaking current operations. Prioritize robust error handling and fallback mechanisms. I also prefer descriptive and expressive variable names.

## System Architecture
The project is built on Django 5.0.6 using Python 3.11, with SQLite for the database. The frontend utilizes Django templates with HTML/CSS.

Key architectural decisions and features include:
-   **Multi-format Document Processing**: Auto-detection and parsing for various document types, including Elastron invoices, Colmol delivery notes, generic documents, and specific Spanish (PEDIDO_ESPANHOL) and French (BON_COMMANDE) purchase order formats. The system intelligently extracts dimensions from product descriptions as a fallback.
-   **OCR Integration**: A multi-engine, cascading OCR approach is implemented for local, offline processing, enhancing accuracy and reliability. This includes QR code detection.
-   **LLM Integration**: Groq LLM (Llama-3.3-70B) is used for intelligent, multi-page document processing, structuring text extracted by OCR into JSON, especially for unknown document layouts. It operates as a primary processing layer after OCR and before specific parsers.
-   **Format-Specific and Generic Parsers**: Dedicated parsing logic handles known supplier formats, alongside a flexible generic parser with heuristics for unknown formats. This includes handling multi-line product descriptions in various languages.
-   **Purchase Order Matching & Validation**: Features SKU mapping, quantity validation, and exception management for parsing errors and mismatches. The system automatically registers new suppliers and unmapped SKUs encountered in documents.
-   **Bidirectional Document Flow**: Automatic Purchase Order creation from "Notas de Encomenda" and linking with "Guias de Remessa" for comprehensive tracking.
-   **Advanced Illegible File Detection**: A multi-layer validation system detects and reports illegible or malformed documents, automatically creating exception tasks.
-   **User Interface**: A dashboard provides KPIs and document filtering, complemented by an admin interface for catalog management.
-   **Deployment**: Configured for autoscale deployment.

## External Dependencies
-   **OCR Engines** (4-Level Cascade):
    -   **OCR.space API (Level 0)**: Cloud OCR for high accuracy with tables and multi-language support.
    -   **PaddleOCR (Level 1)**: Primary local engine, optimized for Portuguese, Spanish, and French.
    -   **EasyOCR (Level 2)**: Secondary local fallback.
    -   **Tesseract OCR (Level 3)**: Final local fallback with robust processing and Portuguese language pack.
-   **Universal Extraction Tools**:
    -   **Camelot-py**: For PDF table extraction (lattice/stream modes).
    -   **pdfplumber**: For advanced PDF parsing and table detection.
    -   **rapidfuzz**: For fuzzy string matching to detect multi-language fields.
-   **Large Language Model**:
    -   **Groq LLM (Llama-3.3-70B)**: Used for intelligent document text structuring into JSON.
-   **Database**: SQLite (db.sqlite3).