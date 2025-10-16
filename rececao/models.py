from django.db import models

class Supplier(models.Model):
    name = models.CharField(max_length=200, unique=True)
    email = models.EmailField(blank=True, null=True)
    code = models.CharField(max_length=50, unique=True)

    def __str__(self):
        return f"{self.code} - {self.name}"

class PurchaseOrder(models.Model):
    number = models.CharField(max_length=100, unique=True)
    supplier = models.ForeignKey(Supplier, on_delete=models.CASCADE, related_name='purchase_orders')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.number
    
    @property
    def is_complete(self):
        """PO está completa quando TODAS as linhas têm qty_remaining = 0"""
        lines = self.lines.all()
        if not lines.exists():
            return False
        return all(line.is_complete for line in lines)

class POLine(models.Model):
    po = models.ForeignKey(PurchaseOrder, on_delete=models.CASCADE, related_name='lines')
    internal_sku = models.CharField(max_length=120)  # código interno Colmol
    description = models.CharField(max_length=255, blank=True)
    unit = models.CharField(max_length=20, default='UN')
    qty_ordered = models.DecimalField(max_digits=12, decimal_places=2)
    qty_received = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    tolerance = models.DecimalField(max_digits=6, decimal_places=2, default=0)  # tolerância admitida

    class Meta:
        unique_together = ('po','internal_sku')

    def __str__(self):
        return f"{self.po.number} · {self.internal_sku}"
    
    @property
    def qty_remaining(self):
        """Quantidade em falta = pedida - recebida"""
        return self.qty_ordered - self.qty_received
    
    @property
    def is_complete(self):
        """Linha está completa quando qty_remaining <= 0"""
        return self.qty_remaining <= 0

class CodeMapping(models.Model):
    supplier = models.ForeignKey(Supplier, on_delete=models.CASCADE, related_name='code_mappings')
    supplier_code = models.CharField(max_length=120)
    internal_sku = models.CharField(max_length=120)
    qty_ordered = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    confidence = models.FloatField(default=1.0)

    class Meta:
        unique_together = ('supplier','supplier_code')

    def __str__(self):
        return f"{self.supplier.code}:{self.supplier_code} -> {self.internal_sku}"

class InboundDocument(models.Model):
    DOC_TYPES = (
        ('GR','Guia de Remessa'),
        ('FT','Nota de Encomenda'),
    )
    supplier = models.ForeignKey(Supplier, on_delete=models.CASCADE, related_name='inbound_docs')
    doc_type = models.CharField(max_length=2, choices=DOC_TYPES, default='GR')
    number = models.CharField(max_length=120)
    file = models.FileField(upload_to='inbound/')
    received_at = models.DateTimeField(auto_now_add=True)
    parsed_payload = models.JSONField(default=dict, blank=True)  # resultado do OCR/extração
    po = models.ForeignKey(PurchaseOrder, on_delete=models.SET_NULL, null=True, blank=True, related_name='inbound_docs')

    def __str__(self):
        return f"{self.get_doc_type_display()} {self.number} ({self.supplier})"

class ReceiptLine(models.Model):
    inbound = models.ForeignKey(InboundDocument, on_delete=models.CASCADE, related_name='lines')
    supplier_code = models.CharField(max_length=120)
    article_code = models.CharField(max_length=120, blank=True)
    maybe_internal_sku = models.CharField(max_length=120, blank=True)  # resultado do mapping
    description = models.CharField(max_length=255, blank=True)
    unit = models.CharField(max_length=20, default='UN')
    qty_received = models.DecimalField(max_digits=12, decimal_places=2, default=0)

class MatchResult(models.Model):
    inbound = models.OneToOneField(InboundDocument, on_delete=models.CASCADE, related_name='match_result')
    status = models.CharField(max_length=30, default='pending')  # matched / exceptions / pending
    summary = models.JSONField(default=dict, blank=True)  # KPIs do matching (linhas OK, divergências, etc.)
    certified_id = models.CharField(max_length=64, blank=True)  # hash/UUID da receção

class ExceptionTask(models.Model):
    inbound = models.ForeignKey(InboundDocument, on_delete=models.CASCADE, related_name='exceptions')
    line_ref = models.CharField(max_length=120)  # referência da linha (supplier_code / internal_sku)
    issue = models.CharField(max_length=255)  # descrição do problema
    suggested_internal_sku = models.CharField(max_length=120, blank=True)
    suggested_qty = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    resolved = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

class MiniCodigo(models.Model):
    """
    Tabela de mini códigos FPOL para exportação Excel.
    
    Mapeia códigos de fornecedor (identificador) para mini códigos simplificados.
    """
    familia = models.CharField(max_length=50, blank=True)
    mini_codigo = models.CharField(max_length=120, unique=True, db_index=True)
    referencia = models.CharField(max_length=120, blank=True)
    designacao = models.CharField(max_length=500)
    identificador = models.CharField(max_length=120, blank=True, null=True, db_index=True)
    tipo = models.CharField(max_length=50, blank=True)
    
    class Meta:
        verbose_name = 'Mini Código'
        verbose_name_plural = 'Mini Códigos'
        ordering = ['familia', 'mini_codigo']
    
    def __str__(self):
        return f"{self.mini_codigo} - {self.designacao}"
