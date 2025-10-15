# COLMOL - Django Project Setup

## Overview
COLMOL is a Django prototype for intelligent document receipt processing. Its main purpose is to automate document matching between Purchase Orders (PO) and delivery receipts/invoices using OCR simulation, SKU mapping, quantity validation, and digital certification. The project aims to streamline the processing of diverse document formats, manage exceptions gracefully, and provide a comprehensive dashboard for real-time statistics and catalog management.

## User Preferences
I prefer iterative development with clear, concise explanations for any changes or new features. Please ensure that all new functionalities integrate seamlessly with existing systems without breaking current operations. Prioritize robust error handling and fallback mechanisms. I also prefer descriptive and expressive variable names.

## System Architecture
The project is built on Django 5.0.6 using Python 3.11, with SQLite for the database. The frontend utilizes Django templates with HTML/CSS. The system employs a multi-engine OCR approach, primarily using PaddleOCR for its accuracy in Portuguese text and table extraction, with Tesseract OCR as a robust local fallback mechanism.

Key architectural decisions and features include:
-   **Multi-format Document Processing**: Auto-detection and parsing for various document types, including Elastron invoices, Colmol delivery notes, generic documents, and specific Spanish (PEDIDO_ESPANHOL) and French (BON_COMMANDE) purchase order formats.
-   **OCR Integration**: Local, offline OCR processing using PaddleOCR (primary) and Tesseract (fallback) for enhanced accuracy and reliability, including QR code detection. A 4-level cascade OCR system (OCR.space → PaddleOCR → EasyOCR → Tesseract) is implemented for maximum success rates.
-   **LLM Integration**: Groq LLM (Llama-3.3-70B) is used as a definitive solution for universal document extraction and structuring, processing OCR-extracted text into structured JSON.
-   **Format-Specific and Generic Parsers**: Dedicated parsing logic for known supplier formats and a flexible generic parser with heuristics for unknown formats.
-   **Purchase Order Matching & Validation**: SKU mapping, quantity validation, and exception management for parsing errors and mismatches.
-   **Bidirectional Document Flow**: Automatic Purchase Order creation from "Notas de Encomenda" and linking with "Guias de Remessa" for comprehensive tracking.
-   **Advanced Illegible File Detection**: Multi-layer validation system to detect and report illegible or malformed documents, automatically creating exception tasks.
-   **User Interface**: Dashboard for KPIs, document filtering, and an admin interface for catalog management.
-   **Deployment**: Configured for autoscale deployment.
-   **Excel Export Enhancements**: Intelligent dimension extraction from descriptions and the use of a "Mini Códigos FPOL" mapping system for standardized Excel exports.
-   **Robustness**: Comprehensive None-safety implemented across product processing functions to handle missing product codes gracefully.

## External Dependencies
-   **OCR Engines**:
    -   **OCR.space API**: Cloud OCR (Level 0) for multi-language, accurate table extraction.
    -   **PaddleOCR**: Primary local engine (Level 1) for fast and accurate Portuguese, Spanish, French processing.
    -   **EasyOCR**: Secondary local fallback (Level 2) for when PaddleOCR fails.
    -   **Tesseract OCR**: Final local fallback (Level 3) with Portuguese language pack.
-   **Large Language Model**:
    -   **Groq API**: Utilizes Llama-3.3-70B for universal, fast, multi-language document text structuring into JSON.
-   **Universal Extraction Tools**:
    -   **Camelot-py**: PDF table extraction (lattice/stream modes).
    -   **pdfplumber**: Advanced PDF parsing and table detection.
    -   **rapidfuzz**: Fuzzy string matching for multi-language field detection.
-   **Database**: SQLite (db.sqlite3).

## Recent Changes

### October 15, 2025 - Bug Fix: Elastron Faturas - Corrigir Extração de Quantidade vs Volume
- **Problem**: Fatura específica FWH_25EU_N5595 extraía valores da coluna "Vol." (volumes/rolos) em vez de "Quant." (quantidade real)
  - Tabela Elastron tem: Artigo, Descrição, Lote, **Quant.**, Un., **Vol.**, Preço, Desconto, IVA, Total
  - LLM confundia as duas colunas numéricas (ex: 34,00 ML vs 1 volume)
- **Root Cause**: Groq LLM prompt não distinguia entre quantidade (metros/peças) e volumes (número de rolos)
- **Solution**: Prompt atualizado com regras específicas para faturas Elastron:
  - ⚠️ QUANTITY EXTRACTION RULES: "Quant." = quantidade real (usar) / "Vol." = volumes (ignorar)
  - Preferir valores decimais (Quant.) sobre inteiros pequenos (Vol.)
  - Exemplo: "Quant.: 34,00 ML | Vol.: 1" → quantidade = 34.0 (NOT 1)
  - Documentada ordem correta das colunas Elastron no prompt
- **Impact**: Faturas Elastron agora extraem quantidade correta mesmo quando têm coluna de volumes
- **Testing**: Utilizador deve testar com documento FWH_25EU_N5595 via interface web Django

### October 15, 2025 - Mini Códigos FPOL: Sistema de Mapeamento para Exportação Excel
- **Feature**: Tabela de mini códigos FPOL adicionada à base de dados para simplificar exportações Excel
- **Modelo MiniCodigo**: Nova tabela com 177 registos importados do Excel do utilizador
  - Campos: `familia`, `mini_codigo` (unique), `referencia`, `designacao`, `identificador` (db_index), `tipo`
  - Mapeia códigos de fornecedor (identificador) → mini códigos simplificados
  - Admin Django: filtros por familia/tipo, busca por mini_codigo/designacao/identificador
- **Comando Django**: `import_mini_codigos` para importar/atualizar mini códigos de ficheiros Excel
  - Validação: mini_codigo obrigatório, update_or_create automático
  - Logging: progresso cada 100 registos + sumário final
  - Teste: 177 códigos importados com sucesso
- **Exportação Excel Modificada**: Nova hierarquia de priorização
  - **🎯 PRIORIDADE 1**: Consulta BD usando `article_code` → `identificador`
  - **PRIORIDADE 2**: Se não encontrar, consulta BD usando `supplier_code` → `identificador`
  - **Fallback 3**: Mini código do payload (documento OCR)
  - **Fallback 4**: `maybe_internal_sku`
  - **Fallback 5**: `article_code` original
  - **Bonus**: Se encontrar na BD e sem descrição, usa `designacao` da BD
- **Colunas Excel**: Mini Código, Dimensões (LxCxE), Quantidade
- **Impact**: Exportações agora usam mini códigos padronizados da BD em vez de códigos internos variáveis
- **Performance**: Acceptable para volumes típicos (2 queries por linha), pode otimizar com cache se necessário