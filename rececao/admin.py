
from django.contrib import admin
from .models import Supplier, PurchaseOrder, POLine, CodeMapping, InboundDocument, ReceiptLine, MatchResult, ExceptionTask, MiniCodigo

admin.site.register(Supplier)
admin.site.register(PurchaseOrder)
admin.site.register(POLine)
admin.site.register(CodeMapping)
admin.site.register(InboundDocument)
admin.site.register(ReceiptLine)
admin.site.register(MatchResult)
admin.site.register(ExceptionTask)

@admin.register(MiniCodigo)
class MiniCodigoAdmin(admin.ModelAdmin):
    list_display = ('mini_codigo', 'familia', 'designacao', 'identificador', 'tipo')
    list_filter = ('familia', 'tipo')
    search_fields = ('mini_codigo', 'designacao', 'identificador', 'referencia')
    ordering = ('familia', 'mini_codigo')
