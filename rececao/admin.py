
from django.contrib import admin
from .models import Supplier, PurchaseOrder, POLine, CodeMapping, InboundDocument, ReceiptLine, MatchResult, ExceptionTask

admin.site.register(Supplier)
admin.site.register(PurchaseOrder)
admin.site.register(POLine)
admin.site.register(CodeMapping)
admin.site.register(InboundDocument)
admin.site.register(ReceiptLine)
admin.site.register(MatchResult)
admin.site.register(ExceptionTask)
