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

## Recent Changes

### October 15, 2025 - Bug Fix: Quantity Validation Now Uses PO Instead of CodeMapping
- **Problem**: Sistema comparava quantidade recebida (Guia) com `mapping.qty_ordered` (valor histórico do CodeMapping) em vez da quantidade encomendada na Purchase Order
- **Example Bug**: Guia com 4000 unidades vs PO com 2000 unidades → sistema não detectava porque comparava com CodeMapping.qty_ordered
- **Solution**: Correção completa da validação de quantidades (linhas 2836-2859 em services.py):
  1. **Busca POLine correspondente**: `poline = inbound.po.lines.filter(internal_sku=mapping.internal_sku).first()`
  2. **Verifica se produto existe na PO**: Se não → exceção "Produto não consta na Purchase Order {po.number}"
  3. **Compara com quantidade REAL da PO**: `qty_ordered = float(poline.qty_ordered or 0)`
  4. **Se exceder**: exceção "Quantidade excedida (recebida X vs encomendada Y)" com valores corretos
- **Impact**: Exceções agora mostram valores REAIS da Purchase Order vinculada, não valores históricos do CodeMapping
- **Tested**: ✅ Validado com documento real - NPZ189008800120 (4000 vs 2000) e NPZ189010300170 (2000 vs 1000) mostram quantidades corretas

### October 15, 2025 - Intelligent PO Matching for Delivery Receipts (Guias de Remessa)
- **Feature**: Sistema agora identifica automaticamente a Purchase Order correta para Guias de Remessa baseado em fornecedor e produtos
- **How it Works**: Quando processa Guia de Remessa sem número de PO explícito:
  1. **Primeiro tenta pelo número da PO** extraído do documento (comportamento padrão)
  2. **Se não encontrar → Matching Inteligente**:
     - Extrai SKUs dos produtos da Guia
     - Busca todas as POs do fornecedor (ordenadas por mais recente)
     - Para cada PO, compara SKUs dos produtos da Guia com POLines
     - Calcula score: `(produtos_coincidentes / total_produtos_guia) × 100`
     - **Vincula automaticamente se score ≥ 70%**
  3. **Se score < 70% ou nenhuma PO encontrada**:
     - Cria ExceptionTask detalhada com score e produtos coincidentes
     - Permite revisão e vinculação manual
- **Smart Exception Handling**:
  - Score insuficiente (< 70%): "PO não identificada com certeza (melhor match: X%, mínimo: 70%)"
  - Nenhuma PO: "Nenhuma PO encontrada para fornecedor X com produtos correspondentes"
  - Fornecedor não definido: "Selecione fornecedor manualmente ou verifique se documento contém NIF válido"
- **Auditability**: Detalhes do matching salvos em `payload['po_matching']`:
  - `method: 'intelligent_matching'`
  - `score: 85.5` (exemplo)
  - `details: { produtos_coincidentes: [...], produtos_guia: [...], produtos_po: [...] }`
- **Robustness**:
  - ✅ Funciona com Guias parciais (nem todos os produtos da PO)
  - ✅ Suporta múltiplos formatos de SKU (artigo, codigo, supplier_code, article_code)
  - ✅ Safe guard: verifica supplier antes de processar (evita crashes)
  - ✅ Logging detalhado para debug (score de cada PO, produtos comparados)
- **Impact**: Guias de Remessa são vinculadas automaticamente à PO correta mesmo sem número de PO explícito no documento
- **Threshold**: 70% escolhido para balancear precisão vs cobertura (pode ser ajustado se necessário)

### October 15, 2025 - Auto-Registration of New Suppliers from Document NIF
- **Feature**: Sistema agora registra automaticamente fornecedores novos detectados em documentos
- **Behavior**: Quando processa qualquer documento (Nota de Encomenda ou Guia):
  - ✅ Extrai NIF e nome do fornecedor do payload parseado (OCR/LLM)
  - ✅ Usa `Supplier.objects.get_or_create(code=NIF)` para criar fornecedor se não existir
  - ✅ Define name = nome extraído ou "Fornecedor {NIF}" se nome não disponível
  - ✅ Atualiza `inbound.supplier` se fornecedor extraído for diferente do selecionado no upload
  - ✅ Safe None handling: `(payload.get("nif") or "").strip()` evita AttributeError
  - ✅ Garante que PO é criada com o fornecedor correto do documento
- **Impact**: Documentos de fornecedores novos são processados automaticamente sem necessidade de cadastro prévio
- **Database Safety**: Usa atomic get_or_create, protege unique constraint em Supplier.code
- **Robustness**: Processa normalmente mesmo quando NIF/fornecedor não são extraídos (None/vazio)

### October 15, 2025 - Auto-Registration of Unmapped SKUs in Notas de Encomenda
- **Feature**: Sistema agora registra automaticamente códigos não mapeados em vez de criar exceções
- **Behavior Change**: Quando processa Nota de Encomenda com SKU não mapeado:
  - ✅ Cria automaticamente CodeMapping usando `get_or_create` (evita race conditions)
  - ✅ Define internal_sku = supplier_code (pode ser ajustado depois)
  - ✅ Define qty_ordered = qty_received (quantidade de referência)
  - ✅ Valida código não vazio antes de criar (evita IntegrityError)
  - ✅ Mantém verificação de quantidade (over-receipt detection)
  - ❌ NÃO cria exceção "Código não mapeado para SKU interno"
- **Impact**: Notas de Encomenda com produtos novos são processadas automaticamente, sem exceções
- **Validation**: Códigos vazios ou inválidos ainda geram exceção apropriada
- **Database Safety**: Usa atomic get_or_create, protege unique_together constraint