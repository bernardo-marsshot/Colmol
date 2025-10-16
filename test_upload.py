#!/usr/bin/env python
"""
Script de teste para fazer upload do PDF e verificar extração
"""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'colmolsite.settings')
django.setup()

from rececao.services import extract_text_from_pdf, parse_portuguese_document

pdf_path = 'attached_assets/10000646_40245000_20250729_1760605207627.PDF'

print('📤 TESTE DE EXTRAÇÃO COM NOVA LÓGICA')
print('='*80)
print(f'PDF: {os.path.basename(pdf_path)}')
print()

# Extrair texto (vai testar a nova lógica de detecção)
print('🔄 Extraindo texto do PDF...')
print()

text, qr_codes = extract_text_from_pdf(pdf_path)

print()
print(f'✅ Texto extraído: {len(text)} caracteres')
print(f'✅ QR codes: {len(qr_codes)}')
print()

# Parsear documento
print('🔄 Parseando documento...')
print()

result = parse_portuguese_document(text, qr_codes, file_path=pdf_path)

print()
print('='*80)
print('RESULTADO DO PROCESSAMENTO:')
print(f'Número documento: {result.get("numero_requisicao")}')
print(f'Número PO: {result.get("po_number")}')
print(f'Fornecedor: {result.get("supplier_name")}')
print(f'Data: {result.get("delivery_date")}')
print(f'Total linhas: {result.get("totals", {}).get("total_lines")}')
print(f'Total quantidade: {result.get("totals", {}).get("total_quantity")}')
print()

if result.get("lines"):
    print(f'PRODUTOS EXTRAÍDOS ({len(result["lines"])} total):')
    for i, line in enumerate(result["lines"][:30], 1):
        code = line.get("product_code", "N/A")
        desc = line.get("description", "N/A")[:40]
        qty = line.get("quantity", 0)
        print(f'  {i:2d}. {code} - Qtd: {qty} - {desc}')
    
    if len(result["lines"]) > 30:
        print(f'  ... (+{len(result["lines"]) - 30} produtos)')
    
    print()
    print(f'✅ TOTAL DE PRODUTOS EXTRAÍDOS: {len(result["lines"])}')
    
    if len(result["lines"]) > 24:
        print(f'✅ SUCESSO! OCR extraiu {len(result["lines"])} produtos (PyPDF2 tinha apenas 24)')
    else:
        print(f'⚠️ Ainda com {len(result["lines"])} produtos - precisa ajuste')

print('='*80)
