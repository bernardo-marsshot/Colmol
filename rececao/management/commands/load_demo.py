
from django.core.management.base import BaseCommand
from rececao.models import Supplier, PurchaseOrder, POLine, CodeMapping

class Command(BaseCommand):
    help = "Carrega dados de demonstração (fornecedor, PO, linhas, mappings)"
    def handle(self, *args, **kwargs):
        s, _ = Supplier.objects.get_or_create(code="F001", defaults={"name":"Fornecedor 1","email":"for1@example.com"})
        po, _ = PurchaseOrder.objects.get_or_create(number="PO-2025-0001", supplier=s)
        POLine.objects.get_or_create(po=po, internal_sku="INT-BL-D23-150", defaults={"description":"Bloco D23 150","qty_ordered":20,"tolerance":0.5})
        POLine.objects.get_or_create(po=po, internal_sku="INT-BL-D23-100", defaults={"description":"Bloco D23 100","qty_ordered":10,"tolerance":0.5})
        CodeMapping.objects.get_or_create(supplier=s, supplier_code="Bl D23 E150", defaults={"internal_sku":"INT-BL-D23-150","confidence":0.98})
        CodeMapping.objects.get_or_create(supplier=s, supplier_code="Bl D23 E100", defaults={"internal_sku":"INT-BL-D23-100","confidence":0.97})
        self.stdout.write(self.style.SUCCESS("Dados de demonstração carregados."))
