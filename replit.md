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

### October 17, 2025 - Parser Especializado para Guias FLEXIPOL/EUROSPUMA
- **Novo Parser Criado**: `parse_guia_flexipol()` em `services.py` (linhas 1323-1413)
  - Desenvolvido para documentos FLEXIPOL/EUROSPUMA com layout em colunas verticais
  - Regex expandido para capturar todos os tipos de código: `^N[A-Z]{2,3}\d+$`
    - Suporta: NIU, NIJ, NND, NNF, NPZ, NUF, NZF, NKN, etc
    - Filtra "NIF" que não é código de produto
  - Lógica de códigos únicos: extrai apenas primeira ocorrência de cada código (produtos principais em negrito)
  - Estrutura detectada: códigos aparecem repetidos em múltiplas colunas (layout colunar do PDF)
- **Detecção Automática**: Integrado na cascata de detecção de documentos
  - Acionado quando detecta "FLEXIPOL" ou "EUROSPUMA" no texto
  - Prioridade após parsers Elastron e Colmol
- **Dados Extraídos**:
  - Código do produto (artigo)
  - Descrição PLACA com dimensões (extraídas via regex)
  - Lote de produção
  - Quantidade (primeira quantidade de cada produto único)
  - Unidade (UN, MT, ML, M²)
  - Número de pedido/encomenda
- **Limitações Conhecidas**:
  - PyMuPDF não preserva informação de formatação (negrito)
  - Não é possível distinguir visualmente produtos principais de subtotais
  - Parser usa heurística de códigos únicos (pode precisar ajuste fino baseado em testes reais)
- **Validação Pendente**: Aguardando teste com documento real para confirmar extração correta dos 41 produtos esperados

### October 16, 2025 - Integração PyMuPDF para Melhor Extração de Tabelas
- **Nova Biblioteca**: Instalado PyMuPDF (fitz v1.26.5) para extração avançada de PDF
- **Função Criada**: `extract_text_with_pymupdf()` em `services.py` (linhas 659-705)
  - Percorre todas as páginas do PDF usando iteração explícita
  - Preserva layout original usando flags: `TEXT_PRESERVE_WHITESPACE | TEXT_PRESERVE_LIGATURES | TEXT_PRESERVE_IMAGES`
  - Identifica páginas individualmente com marcador "--- Página N ---"
  - Integra detecção de QR codes quando disponível
- **Cascata de Extração Atualizada** (função `extract_text_from_pdf` linha 708):
  - **LEVEL 0**: PyMuPDF (novo) - preserva layout, ideal para tabelas
  - **LEVEL 1**: PyPDF2 - fallback rápido para texto embutido
  - **LEVEL 2**: OCR.space API - cloud OCR
  - **LEVEL 3**: PaddleOCR/EasyOCR/Tesseract - engines locais
- **Benefícios**:
  - Leitura completa de todas as páginas do documento
  - Layout preservado (crítico para documentos com tabelas)
  - Espaços em branco mantidos para estrutura correta
  - Fallback robusto se PyMuPDF falhar
- **Validação**: Logs do servidor confirmam extração bem-sucedida de PDFs de 1-2 páginas (492-4696 chars)

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