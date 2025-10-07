#!/usr/bin/env python
# llm_extraction/run_gemini_ingest.py
"""
Script CLI para testar extração de documentos com Google Gemini (GRATUITO).

Uso:
    python llm_extraction/run_gemini_ingest.py <caminho_pdf> [--dry-run] [--model gemini-2.5-flash]

Exemplos:
    python llm_extraction/run_gemini_ingest.py attached_assets/FT_ELASTRON_8800093.pdf
    python llm_extraction/run_gemini_ingest.py attached_assets/GR_COLMOL_12345.pdf --dry-run
"""

import os
import sys
import argparse
import pdfplumber
from dotenv import load_dotenv

# Carregar variáveis de ambiente
load_dotenv()

def setup_django():
    """Configura Django para acesso aos models."""
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "colmolsite.settings")
    import django
    django.setup()

def extract_text_from_pdf(pdf_path: str) -> str:
    """Extrai texto do PDF com pdfplumber (sem OCR)."""
    pages = []
    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages):
            text = page.extract_text() or ""
            if text.strip():
                pages.append(f"--- PÁGINA {i+1} ---\n{text}")
    return "\n\n".join(pages)

def build_user_prompt(raw_text: str, file_path: str) -> str:
    """Constrói prompt user com texto do PDF e esquema JSON."""
    return f"""
CONTEXTO - Modelos Django alvo:
- Supplier(code unique, name)
- PurchaseOrder(number unique, supplier)
- InboundDocument(supplier, doc_type in {{GR, FT}}, number, file, parsed_payload, po?)
- ReceiptLine(inbound, supplier_code, article_code, maybe_internal_sku?, description, unit, qty_received)

FICHEIRO: {file_path}

TEXTO EXTRAÍDO DO DOCUMENTO:

{raw_text}

---

Devolve JSON seguindo o esquema indicado no system prompt.
"""

def main():
    parser = argparse.ArgumentParser(
        description="Extração de documentos PT via Google Gemini (GRATUITO)"
    )
    parser.add_argument("pdf", help="Caminho do PDF a processar")
    parser.add_argument(
        "--dry-run", 
        action="store_true", 
        help="Mostrar JSON extraído sem gravar na base de dados"
    )
    parser.add_argument(
        "--model", 
        default="gemini-2.5-flash", 
        help="Modelo Gemini (padrão: gemini-2.5-flash = GRATUITO)"
    )
    args = parser.parse_args()

    # Verificar ficheiro
    if not os.path.exists(args.pdf):
        print(f"❌ Ficheiro não encontrado: {args.pdf}")
        sys.exit(1)

    # Setup Django
    print("🔧 A configurar Django...")
    setup_django()

    # Carregar prompt do sistema
    prompt_path = "llm_extraction/prompts/system_prompt.txt"
    if not os.path.exists(prompt_path):
        print(f"❌ System prompt não encontrado: {prompt_path}")
        sys.exit(1)
    
    with open(prompt_path, "r", encoding="utf-8") as f:
        system_prompt = f.read()

    # Importar após Django setup
    from llm_extraction.gemini_client import call_gemini
    from llm_extraction.gemini_persist import persist_document
    import json

    # Extrair texto
    print(f"📄 A extrair texto de: {args.pdf}")
    raw_text = extract_text_from_pdf(args.pdf)
    
    if len(raw_text) < 50:
        print(f"⚠️ AVISO: Texto extraído muito curto ({len(raw_text)} chars)")
        print("   PDF pode ser imagem pura (sem texto embutido)")
        print("   Para PDFs escaneados, usa o sistema OCR Tesseract existente")
    
    print(f"✅ Texto extraído: {len(raw_text)} caracteres")

    # Preparar prompts
    rel_file = os.path.basename(args.pdf)
    user_prompt = build_user_prompt(raw_text, file_path=rel_file)

    # Chamar Gemini
    print(f"🤖 A chamar Gemini API ({args.model})...")
    try:
        extracted_data = call_gemini(system_prompt, user_prompt, model=args.model)
        
        # Adicionar file_path
        extracted_data["file_path"] = rel_file
        
        print("✅ Extração concluída!")
        print("\n" + "="*60)
        print("JSON EXTRAÍDO:")
        print("="*60)
        print(json.dumps(extracted_data, indent=2, ensure_ascii=False))
        print("="*60)
        
        if args.dry_run:
            print("\n🔍 DRY-RUN: Dados NÃO foram gravados na base de dados")
            sys.exit(0)
        
        # Persistir
        print("\n💾 A gravar na base de dados...")
        inbound = persist_document(extracted_data)
        print(f"✅ Documento gravado: {inbound}")
        print(f"   - Supplier: {inbound.supplier.name}")
        print(f"   - Tipo: {inbound.doc_type}")
        print(f"   - Número: {inbound.number}")
        print(f"   - Linhas: {inbound.lines.count()}")
        
    except Exception as e:
        print(f"❌ ERRO: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
