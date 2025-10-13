#!/usr/bin/env python
import os
import sys
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'colmolsite.settings')
django.setup()

from rececao.services import real_ocr_extract

test_file = "media/inbound/11-082873_0VJmQs7.pdf"

print(f"\n{'='*80}")
print(f"🧪 TESTE SISTEMA MULTI-OCR")
print(f"{'='*80}")
print(f"📄 Arquivo: {test_file}")
print(f"{'='*80}\n")

result = real_ocr_extract(test_file)

print(f"\n{'='*80}")
print(f"📊 RESULTADO FINAL")
print(f"{'='*80}")
print(f"Estratégia usada: {result.get('strategy_used', 'N/A')}")
print(f"Texto extraído: {len(result.get('text', ''))} caracteres")
print(f"Produtos encontrados: {len(result.get('produtos', []))} produtos")
print(f"QR codes: {len(result.get('qr_codes', []))} encontrados")
print(f"{'='*80}\n")
