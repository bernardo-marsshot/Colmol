#!/usr/bin/env python
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'colmolsite.settings')
django.setup()

from rececao.models import InboundDocument, Supplier, ExceptionTask
from rececao.services import real_ocr_extract, create_po_from_nota_encomenda
from django.db import transaction

# Deletar documento anterior e reprocessar
print("🗑️  Deletando documento anterior...")
InboundDocument.objects.filter(id=99).delete()

# Obter fornecedor
supplier = Supplier.objects.get(code="AUTO")
print(f"📋 Usando fornecedor: {supplier.name}")

# Criar novo InboundDocument
file_path = 'inbound/nota_encomenda_1760356779.pdf'
inbound = InboundDocument.objects.create(
    supplier=supplier,
    doc_type='FT',  # Nota de Encomenda
    number='NOTA-1760356779',
    file=file_path
)

print(f"📄 InboundDocument criado: ID={inbound.id}, Número={inbound.number}")

# Executar OCR com configurações melhoradas
print("\n🔄 Processando documento com OCR melhorado (DPI 300, timeout 60s)...")
payload = real_ocr_extract(inbound.file.path)

if payload.get("error"):
    print(f"❌ Erro OCR: {payload['error']}")
    ExceptionTask.objects.create(
        inbound=inbound,
        line_ref="OCR",
        issue=f"OCR extraction failed: {payload['error']}")
else:
    print(f"✅ OCR bem sucedido!")

inbound.parsed_payload = payload
inbound.save()

# Criar PO se for Nota de Encomenda
print(f"\n📋 Criando PurchaseOrder a partir da Nota...")
po = create_po_from_nota_encomenda(inbound, payload)

if po:
    print(f"✅ PO criada: {po.number}")
    print(f"   - Fornecedor: {po.supplier.name}")
    print(f"   - Linhas: {po.lines.count()}")
    
    if po.lines.count() > 0:
        print(f"\n📦 Produtos extraídos (primeiros 15):")
        for line in po.lines.all()[:15]:
            print(f"   - {line.internal_sku}: {line.description[:60]} (qty: {line.qty_ordered} {line.unit})")
    else:
        print("\n⚠️  Nenhum produto extraído - verificar qualidade do OCR")
        
        # Mostrar preview do texto extraído
        texto = payload.get("texto_completo", "")
        if texto:
            print(f"\n📝 Texto extraído (primeiros 500 chars):")
            print(texto[:500])
        else:
            print("\n❌ Nenhum texto extraído do documento")
else:
    print("❌ Falha ao criar PO")

print(f"\n🌐 Ver detalhes em: /inbound/{inbound.id}/")
print(f"🌐 Ver PO em: /po/")
