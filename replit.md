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
- **Number Normalization**: Universal system for normalizing numbers based on digit count after the comma (3 digits = thousands separator, 1-2 digits = decimal).
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

## Recent Changes

### October 16, 2025 - Correção: Detecção Inteligente de Headers Não Estruturados (Força OCR.space)
- **Problema Identificado**: PyPDF2 extrai headers/cabeçalhos mas não consegue ler produtos visuais de PDFs Flexibol
- **Comportamento Anterior**:
  - PyPDF2 extraía cabeçalhos (PEDIDO/ORDER, CÓDIGO/PART NUMBER, etc.)
  - PyPDF2 extraía códigos e quantidades MAS em linhas separadas (desorganizados)
  - Sistema pensava que tinha texto suficiente e não usava OCR.space
  - OCR.space nunca era ativado, produtos das páginas 2+ eram perdidos
- **Correção Aplicada** (funções `has_only_headers_no_products` e `extract_text_from_pdf` em `rececao/services.py`):
  - **Nova função `has_only_headers_no_products()`** (linhas ~710-771):
    - Detecta quando PyPDF2 extrai headers mas sem linhas estruturadas
    - Verifica se há linhas com SKU + descrição + quantidade REAL (com unidade) juntos
    - Quantidade REAL: número + unidade obrigatória (UN, KG, CX, etc.)
    - Evita falsos positivos de dimensões (ex: 1980x0880x0020)
    - Não depende de palavra "continua" - detecção estrutural pura
  - **Modificação em `extract_text_from_pdf()`** (linhas ~773-820):
    - Se PyPDF2 retorna texto mas é só headers → força OCR.space
    - OCR.space lê produtos visuais de TODAS as páginas
    - Aplica `remove_repeated_headers()` para limpar headers duplicados
  - **Função `remove_repeated_headers()`** (linhas ~682-707):
    - Remove cabeçalhos repetidos entre páginas
    - Remove palavra "continua" e variações
    - Mantém apenas dados de produtos limpos
- **Benefícios**:
  - Documentos Flexibol multipáginas agora processados completamente
  - Sistema força OCR.space quando PyPDF2 não consegue estruturar dados
  - Detecção robusta sem depender de palavras-chave específicas
  - Aceita SKUs variados (ABC123, 19607542/01, E0748001901, etc.)
  - Elimina falsos positivos causados por dimensões de produtos
  - Suporta unidades variadas (UN, KG, M, L, PC, PCS, CX, UNID, CAIXA)

### October 16, 2025 - Correção: Extração de Produtos de TODAS as Páginas PDF (Fornecedores Multipáginas)
- **Problema Identificado**: Função `universal_table_extract` só executava pdfplumber quando Camelot não encontrava produtos
- **Comportamento Anterior**:
  - Se Camelot encontrasse produtos na página 1, pdfplumber nunca era executado
  - Produtos nas páginas 2, 3, etc. eram ignorados
  - Especialmente problemático para fornecedores como Flexibol com documentos multipáginas
- **Correção Aplicada** (linha 2127 em `rececao/services.py`):
  - Removida condição `and len(produtos) == 0` da verificação do pdfplumber
  - **Antes**: `if PDFPLUMBER_AVAILABLE and file_path.lower().endswith('.pdf') and len(produtos) == 0:`
  - **Depois**: `if PDFPLUMBER_AVAILABLE and file_path.lower().endswith('.pdf'):`
  - Agora pdfplumber SEMPRE processa TODAS as páginas do PDF
- **Benefícios**:
  - Extração completa de produtos de documentos multipáginas
  - Camelot e pdfplumber trabalham em conjunto para máxima cobertura
  - Resolve problema específico de fornecedores como Flexibol que enviam documentos com múltiplas páginas de produtos

### October 16, 2025 - Correção: Normalização Consistente de Números em Todos os Parsers
- **Problema Identificado**: Função `normalize_number` aninhada em `parse_fatura_elastron` sobrescrevia a função global
- **Função Aninhada Removida** (linhas 1109-1128):
  - Implementação antiga **não** seguia regra de 3 dígitos
  - Tratava vírgula sempre como decimal (formato PT: 1.234,56)
  - Causava inconsistência entre parsers diferentes
- **Correção Aplicada**:
  - Removida função aninhada duplicada
  - Agora todos os parsers usam a função global `normalize_number` (linha 39)
  - Implementação correta da regra universal de 3 dígitos
- **Regra de Normalização Confirmada**:
  - **3 dígitos após vírgula** = separador de milhares (remover vírgula)
    - Exemplos: `190,000 → 190000.0`, `200,090 → 200090.0`, `1,880 → 1880.0`
  - **1-2 dígitos após vírgula** = decimal normal (substituir vírgula por ponto)
    - Exemplos: `190,5 → 190.5`, `2,5 → 2.5`, `34,00 → 34.0`
- **Testes de Validação** (todos ✅):
  ```
  190,000 → 190000.0  (3 dígitos = separador de milhares)
  200,090 → 200090.0  (3 dígitos = separador de milhares)
  1,880 → 1880.0      (3 dígitos = separador de milhares)
  125,000 → 125000.0  (3 dígitos = separador de milhares)
  0,150 → 150.0       (3 dígitos = separador de milhares)
  
  190,5 → 190.5       (1-2 dígitos = decimal normal)
  2,5 → 2.5           (1-2 dígitos = decimal normal)
  34,00 → 34.0        (1-2 dígitos = decimal normal)
  1,88 → 1.88         (1-2 dígitos = decimal normal)
  ```
- **Benefícios**:
  - Normalização consistente em TODOS os parsers (Elastron, Colmol, Genérico, LLM)
  - Regra de 3 dígitos aplicada uniformemente em todo o sistema
  - Sem duplicação de lógica de normalização
  - Documentação clara na função global com exemplos