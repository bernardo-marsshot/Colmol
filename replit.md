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

## Recent Changes

### October 16, 2025 - Feature: Múltiplas POs por Documento
- **Nova Funcionalidade**: Documentos com múltiplas encomendas agora criam uma PO separada para cada
- **Implementação**:
  - LLM (Groq/Ollama) extrai `numero_encomenda` por produto
  - Sistema agrupa produtos por `numero_encomenda`
  - Cria PO dedicada para cada grupo com produtos corretos
  - Fallback: se produto sem `numero_encomenda`, usa número do documento
- **Exemplo**: Documento com Encomenda 11-161050 (2 produtos) e Encomenda 11-161594 (3 produtos) → cria 2 POs separadas
- **Compatibilidade**: Documentos com encomenda única continuam funcionando normalmente
- **Architect Review**: Agrupamento e criação de POs aprovados, sem regressões

### October 16, 2025 - Correção: Agregação de Quantidades em POs Duplicadas
- **Bug Fix**: Produtos duplicados em múltiplas encomendas agora agregam quantidades automaticamente
- **Problema Resolvido**: 
  - Notas de Encomenda com múltiplas encomendas continham produtos repetidos
  - Sistema falhava com `UNIQUE constraint failed: rececao_poline.po_id, rececao_poline.internal_sku`
  - Erro de tipo: `unsupported operand type(s) for +=: 'decimal.Decimal' and 'float'`
- **Solução Implementada**:
  - Substituído `POLine.objects.create()` por `get_or_create()`
  - Quando produto já existe na PO → soma quantidades automaticamente
  - Conversão `Decimal(str(...))` para compatibilidade com DecimalField
  - Log mostra agregação: "📊 Agregado X unidades ao produto Y (total: Z)"
- **Benefícios**:
  - Documentos complexos processados sem erros
  - Quantidades corretas (soma de todas ocorrências)
  - Descrição e unidade preservadas da primeira ocorrência
  - Precisão numérica mantida com Decimal
- **Architect Review**: Correção aprovada - quantidades agregadas corretamente, sem regressões

### October 16, 2025 - Correção: Vinculação de PO Antes de Exceções
- **Bug Fix**: Vinculação de PO agora acontece ANTES de qualquer exceção ou matching
- **Ordem de Processamento Corrigida**:
  1. Criar linhas de receção
  2. **Vincular PO** (usando `po_number` ou `document_number` do payload)
  3. **Se GR sem PO** → adicionar exceção "PO não identificada" ao array (antes do matching)
  4. Matching (apenas se tiver PO)
  5. Recriar exceções (preserva exceção de PO)
- **Problema Resolvido**: 
  - Anteriormente, exceção "PO não identificada" era criada após matching
  - Agora é criada ANTES, mostrando número extraído para debug
- **Benefícios**:
  - Exceções aparecem na ordem correta
  - Número da PO extraído é mostrado mesmo quando não encontrada
  - Evita tentativas de matching sem PO vinculada
- **Architect Review**: Bug de exceção deletada corrigido - exceção é preservada corretamente

### October 16, 2025 - Feature: Matching por Linha para GR com Múltiplas POs
- **Nova Funcionalidade**: GR pode fazer matching usando PO específica de cada produto
- **Implementação**:
  - Adicionado campo `po_number_extracted` em `ReceiptLine` (migration 0006)
  - LLM extrai `numero_encomenda` por produto e salva em `po_number_extracted`
  - Loop de matching busca PO específica para cada linha:
    - Se linha tem `po_number_extracted` → busca essa PO
    - Se PO específica encontrada → usa para matching
    - Senão → usa `inbound.po` padrão (fallback)
    - Se nenhuma PO disponível → cria exceção por linha
- **Fluxo Corrigido**:
  - GR sem `inbound.po` agora entra no matching (removido bloqueio antecipado)
  - Cada linha busca sua PO independentemente
  - Exceções criadas por linha, não bloqueiam outras
- **Exemplo**: GR com produtos das encomendas 11-161050 e 11-161594
  - Produto A (`po_number_extracted="11-161050"`) → matching com PO 11-161050
  - Produto B (`po_number_extracted="11-161594"`) → matching com PO 11-161594
  - Quantidades decrementadas nas POs corretas
- **Logs**: Mostram qual PO foi usada: "🔍 Produto X → PO específica Y"
- **Compatibilidade**: GR com encomenda única continua funcionando (usa `inbound.po`)
- **Architect Review**: Fluxo aprovado - matching parcial funciona, sem regressões

### October 16, 2025 - Feature: Notas de Encomenda no Dashboard
- **Nova Funcionalidade**: Dashboard agora mostra TODOS os documentos (FT + GR)
- **Implementação**:
  - **views.py**: Removido filtro `doc_type='GR'`, agora usa `InboundDocument.objects.all()`
  - **KPIs focados em GR**: Processado/Exceções/Erro/Pendente contam apenas GR (matching)
  - **Total de Documentos**: Conta todos (FT + GR) para visibilidade completa
  - **template**: Diferenciação visual clara entre tipos:
    - **FT (Nota de Encomenda)**: ícone 📝, PO mostra ✨ (PO criada)
    - **GR (Guia de Remessa)**: ícone 📦, PO mostra 📋 (PO vinculada)
  - **Status separados**:
    - FT: `data-status="ft_success"` ou `data-status="ft_error"` (não conflita com filtros)
    - GR: `data-status="matched|exceptions|error|pending"` (filtros normais)
- **Lógica de Status**:
  - **FT**: ✓ (sucesso) se tem PO criada, ✗ (erro) se não tem PO
  - **GR**: usa `match_result.status` normal
- **Comportamento dos Filtros**:
  - Clicar em "Processado" → filtra apenas GR matched (não FT)
  - Clicar em "Erro" → filtra apenas GR error (não FT sem PO)
  - FT sempre visível na lista, mas não afeta/conflita com filtros de GR
- **Benefícios**:
  - Visibilidade completa do fluxo: Nota de Encomenda → cria PO → Guia de Remessa → matching
  - KPIs claros e focados (apenas matching de GR)
  - Não mistura tipos diferentes de problemas
- **Architect Review**: Aprovado - KPIs isolados corretamente, filtros funcionam sem conflitos

### October 16, 2025 - Feature: Diferenciação de Status 'Error' vs 'Exceptions'
- **Problema Resolvido**: Gráfico tinha fatia "Erro" mas status 'error' não existia no código
- **Implementação**:
  - **services.py**: Nova lógica de status baseada no tipo de problema:
    - Verifica se há `ExceptionTask` com `line_ref="OCR"` (erros críticos de processamento)
    - Se sim → `MatchResult.status = "error"`
    - Se não → lógica normal (`matched` se issues == 0, senão `exceptions`)
  - **Preservação de Exceções de OCR**:
    - Ao deletar exceções antigas: `inbound.exceptions.exclude(line_ref="OCR").delete()`
    - Garante que exceções de OCR persistem entre reprocessamentos
    - Apenas exceções de matching são recriadas
- **Status Semânticos (agora claros)**:
  - 🔴 **error**: Falha no OCR/parsing (ficheiro ilegível, OCR falhou, texto muito curto, >50% produtos inválidos, qualidade de imagem baixa)
  - 🟡 **exceptions**: Problemas no matching (divergências, SKU não encontrado, quantidade excedida, PO não encontrada)
  - 🟢 **matched**: Matching bem-sucedido, tudo OK
  - ⚪ **pending**: Documento ainda não processado
- **Ordem de Operações**:
  1. Verificar se há erros de OCR
  2. Deletar apenas exceções de matching antigas (preserva OCR)
  3. Criar novas exceções de matching
  4. Definir status baseado em tipo de problema
- **Benefícios**:
  - Diferenciação clara entre erros de processamento (OCR) e problemas de negócio (matching)
  - Fatia vermelha "Erro" agora aparece corretamente no gráfico do dashboard
  - Documentos ilegíveis/corrompidos são identificados visualmente
  - Não mistura falhas técnicas com exceções de negócio
- **Architect Review**: Aprovado - exceções de OCR preservadas corretamente, status diferenciado sem regressões

### October 16, 2025 - Feature: Sistema de Retry Progressivo para PDFs Multi-Página
- **Problema Resolvido**: PDFs com múltiplas páginas devem ser processados de forma resiliente
- **Implementação em `extract_text_from_pdf_with_ocr`**:
  - **Rastreamento por Página**: Cada página tem estado independente (`text`, `qr_codes`, `attempts`, `success`)
  - **Loop de Retry Inteligente**:
    - Tenta extrair todas as páginas
    - Se alguma falhar → guarda o que já foi extraído
    - Tenta novamente APENAS as páginas que falharam
    - Repete até 3 tentativas por página
  - **Preservação de Progresso**:
    - Páginas bem-sucedidas não são reprocessadas
    - QR codes salvos apenas na primeira tentativa (evita duplicados)
    - Texto consolidado de todas as páginas que conseguiram ser extraídas
  - **Limite de Tentativas**: Máximo 3 tentativas por página para evitar loops infinitos
  - **Aguardo entre Retries**: 1 segundo entre rounds de retry para dar "tempo de respiração"
- **Exemplo de Fluxo**:
  - **Tentativa 1**: Página 1 ✅, Página 2 ❌, Página 3 ✅
  - **Tentativa 2** (apenas Página 2): Página 2 ✅
  - **Resultado**: 3/3 páginas extraídas, texto consolidado completo
- **Cascata de OCR Mantida**: PaddleOCR → EasyOCR → Tesseract (cada tentativa usa os 3 engines)
- **Benefícios**:
  - PDFs com páginas problemáticas não bloqueiam extração das outras
  - Sistema resiliente: continua tentando até conseguir ou esgotar tentativas
  - Resultados parciais sempre retornados (melhor que falha total)
  - Logs detalhados: `✅ OCR completo: X/Y páginas extraídas`
- **Architect Review**: Aprovado - retry progressivo funciona, progresso preservado, sem loops infinitos