
from django.shortcuts import render, redirect, get_object_or_404
from django.db.models import Sum
from django.http import HttpResponse
from .models import InboundDocument, MatchResult, Supplier, PurchaseOrder
from .forms import InboundUploadForm
from .services import process_inbound, export_document_to_excel

def dashboard(request):
    total_docs = InboundDocument.objects.count()
    matched = MatchResult.objects.filter(status='matched').count()
    exceptions = MatchResult.objects.filter(status='exceptions').count()
    suppliers = Supplier.objects.count()
    latest = InboundDocument.objects.order_by('-received_at')[:10]
    return render(request, 'dashboard.html', {
        'total_docs': total_docs,
        'matched': matched,
        'exceptions': exceptions,
        'suppliers': suppliers,
        'latest': latest,
    })

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
