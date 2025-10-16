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
- **Multi-format Document Processing**: Auto-detection and parsing for various document types, including Elastron invoices, Colmol delivery notes, generic documents, and specific Spanish (PEDIDO_ESPANHOL) and French (BON_COMMANDE) purchase order formats.
- **OCR Integration**: A 4-level cascade OCR system (OCR.space → PaddleOCR → EasyOCR → Tesseract) is implemented for maximum success rates, supporting local, offline processing and QR code detection.
- **LLM Integration**: Groq LLM (Llama-3.3-70B) is used as a definitive solution for universal document extraction and structuring, processing OCR-extracted text into structured JSON.
- **Format-Specific and Generic Parsers**: Dedicated parsing logic for known supplier formats and a flexible generic parser with heuristics for unknown formats.
- **Purchase Order Matching & Validation**: SKU mapping, quantity validation, and exception management for parsing errors and mismatches, including a decremental matching system for tracking received quantities against POs.
- **Bidirectional Document Flow**: Automatic Purchase Order creation from "Notas de Encomenda" and linking with "Guias de Remessa" for comprehensive tracking.
- **Advanced Illegible File Detection**: Multi-layer validation system to detect and report illegible or malformed documents, automatically creating exception tasks.
- **Excel Export Enhancements**: Intelligent dimension extraction from descriptions and the use of a "Mini Códigos FPOL" mapping system for standardized Excel exports, prioritizing database lookups for `mini_codigo` based on `article_code` or `supplier_code`.
- **Robustness**: Comprehensive None-safety across product processing functions and automatic creation of `CodeMapping` for unknown products in incoming documents.
- **Number Normalization**: Universal system for normalizing numbers based on the count of digits after the comma (3 digits for thousands, 1-2 for decimals).
- **LLM Fallback System**: Automatic fallback to a secondary Groq API key and then to Ollama if primary Groq calls fail due to rate limits.

**System Design Choices:**
- Configured for autoscale deployment.
- Emphasizes robust error handling and fallback mechanisms for OCR and LLM integrations.

## External Dependencies
-   **OCR Engines**:
    -   **OCR.space API**: Cloud OCR for multi-language and accurate table extraction.
    -   **PaddleOCR**: Primary local engine for fast and accurate Portuguese, Spanish, French processing.
    -   **EasyOCR**: Secondary local fallback.
    -   **Tesseract OCR**: Final local fallback with Portuguese language pack.
-   **Large Language Model**:
    -   **Groq API**: Utilizes Llama-3.3-70B for universal, fast, multi-language document text structuring into JSON. Includes a fallback mechanism with a secondary API key.
    -   **Ollama**: Used as a final fallback if Groq API calls fail.
-   **Universal Extraction Tools**:
    -   **Camelot-py**: PDF table extraction.
    -   **pdfplumber**: Advanced PDF parsing and table detection.
    -   **rapidfuzz**: Fuzzy string matching for multi-language field detection.
-   **Database**: SQLite (db.sqlite3).