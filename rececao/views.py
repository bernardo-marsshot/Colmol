# views.py
from django.shortcuts import render
from django.db.models import Count
# Ajusta os imports ao teu projeto/app:
from .models import InboundDocument, Supplier  # garante que estes modelos existem no teu app

def dashboard(request):
    # Contagens por estado
    total_docs = InboundDocument.objects.count()
    matched    = InboundDocument.objects.filter(match_result__status='matched').count()
    exceptions = InboundDocument.objects.filter(match_result__status='exception').count()
    errors     = InboundDocument.objects.filter(match_result__status='error').count()

    # Pendente = tudo o que não tem resultado ainda (ou qualquer outro estado não coberto acima)
    pending = total_docs - matched - exceptions - errors
    if pending < 0:
        pending = 0  # salvaguarda, caso existam estados “extra” ou inconsistências

    suppliers = Supplier.objects.count()

    latest = (
        InboundDocument.objects
        .select_related('supplier', 'po', 'match_result')
        .order_by('-received_at')[:10]
    )

    ctx = {
        'total_docs': total_docs,
        'matched': matched,
        'exceptions': exceptions,
        'errors': errors,
        'pending': pending,
        'suppliers': suppliers,
        'latest': latest,
    }
    return render(request, 'dashboard.html', ctx)


def upload_inbound(request):
    msg = None
    if request.method == 'POST':
        form = InboundUploadForm(request.POST, request.FILES)
        if form.is_valid():
            inbound = form.save()
            process_inbound(inbound)
            return redirect('inbound_detail', pk=inbound.pk)
    else:
        form = InboundUploadForm()
    return render(request, 'upload.html', {'form': form})

def inbound_detail(request, pk):
    inbound = get_object_or_404(InboundDocument, pk=pk)
    result = getattr(inbound, 'match_result', None)
    return render(request, 'inbound_detail.html', {'inbound': inbound, 'result': result})

def po_list(request):
    pos = PurchaseOrder.objects.all().order_by('-id')
    return render(request, 'po_list.html', {'pos': pos})

def export_excel(request, pk):
    """Export document to Excel"""
    return export_document_to_excel(pk)
