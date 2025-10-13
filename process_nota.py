#!/usr/bin/env python
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'colmolsite.settings')
django.setup()

from rececao.models import InboundDocument, Supplier
from rececao.services import process_inbound

# Obter ou criar fornecedor
supplier, created = Supplier.objects.get_or_create(
    code="AUTO",
    defaults={'name': 'Fornecedor Auto-Detetado', 'email': 'auto@example.com'}
)

if created:
    print(f"✅ Fornecedor criado: {supplier.name}")
else:
    print(f"📋 Usando fornecedor existente: {supplier.name}")

# Criar InboundDocument
file_path = 'inbound/nota_encomenda_1760356779.pdf'
inbound = InboundDocument.objects.create(
    supplier=supplier,
    doc_type='FT',  # Nota de Encomenda
    number='AUTO-' + str(int(os.path.getmtime(f'media/{file_path}'))),
    file=file_path
)

print(f"📄 InboundDocument criado: ID={inbound.id}, Número={inbound.number}")

# Processar documento (OCR + criação de PO)
print("🔄 Processando documento com OCR...")
result = process_inbound(inbound)

print(f"\n✅ Processamento concluído!")
print(f"   - Status: {result.status if result else 'N/A'}")
print(f"   - Documento ID: {inbound.id}")

if inbound.po:
    print(f"   - PO criada: {inbound.po.number}")
    print(f"   - Linhas na PO: {inbound.po.lines.count()}")
    
    print(f"\n📦 Produtos extraídos:")
    for line in inbound.po.lines.all()[:10]:  # Primeiras 10 linhas
        print(f"   - {line.internal_sku}: {line.description[:50]} (qty: {line.qty_ordered})")
else:
    print("   - Nenhuma PO criada")

print(f"\n🌐 Ver detalhes em: /inbound/{inbound.id}/")
