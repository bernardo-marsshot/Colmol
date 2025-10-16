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
- **OCR Integration**: A 4-level cascade OCR system (OCR.space → PaddleOCR → EasyOCR → Tesseract) ensures maximum success rates, supporting local, offline processing and QR code detection.
- **LLM Integration**: Groq LLM (Llama-3.3-70B) is used for universal document extraction and structuring, processing OCR-extracted text into structured JSON.
- **Format-Specific and Generic Parsers**: Dedicated parsing logic for known supplier formats and a flexible generic parser for unknown formats.
- **Purchase Order Matching & Validation**: SKU mapping, quantity validation, exception management, and a decremental matching system.
- **Bidirectional Document Flow**: Automatic PO creation from "Notas de Encomenda" and linking with "Guias de Remessa".
- **Advanced Illegible File Detection**: Multi-layer validation system detects and reports illegible documents, creating exception tasks.
- **Excel Export Enhancements**: Intelligent dimension extraction and "Mini Códigos FPOL" mapping for standardized Excel exports.
- **Robustness**: Comprehensive None-safety across product processing functions and automatic creation of `CodeMapping` for unknown products.
- **Number Normalization**: Universal system for normalizing numbers based on digit count after the comma.
- **LLM Fallback System**: Automatic fallback to a secondary Groq API key and then to Ollama if primary Groq calls fail.
- **Flexible Product Validation**: Allows product acceptance based on valid description (>=10 chars) and quantity (>0) even without an explicit product code.
- **Multi-PO Handling**: Documents containing multiple purchase orders now result in separate POs being created for each.
- **Quantity Aggregation**: Duplicate products within multiple orders in a single document automatically aggregate quantities.
- **PO Linking Priority**: Purchase Order linking now occurs before any exceptions or matching processes.
- **Line-Item Matching for GR with Multiple POs**: Delivery Receipts can perform matching using a specific PO extracted for each product line item.
- **Dashboard Enhancements**: Dashboard now displays all documents (FT + GR) with clear visual differentiation and separate KPIs for GR matching.
- **Differentiated Status**: Clear distinction between 'Error' (critical processing failures like OCR issues) and 'Exceptions' (business logic problems like matching discrepancies).

**System Design Choices:**
- Configured for autoscale deployment.
- Emphasizes robust error handling and fallback mechanisms for OCR and LLM integrations.

## External Dependencies
-   **OCR Engines**:
    -   **OCR.space API**: Cloud OCR.
    -   **PaddleOCR**: Primary local engine.
    -   **EasyOCR**: Secondary local fallback.
    -   **Tesseract OCR**: Final local fallback (with Portuguese).
-   **Large Language Model**:
    -   **Groq API**: Utilizes Llama-3.3-70B for universal document text structuring.
    -   **Ollama**: Final LLM fallback.
-   **Universal Extraction Tools**:
    -   **Camelot-py**: PDF table extraction.
    -   **pdfplumber**: Advanced PDF parsing.
    -   **rapidfuzz**: Fuzzy string matching.
-   **Database**: SQLite (db.sqlite3).