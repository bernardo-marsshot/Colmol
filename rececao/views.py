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
    
    # Get latest document statistics for line reading chart
    latest_doc = InboundDocument.objects.select_related('supplier', 'po', 'match_result').order_by('-received_at').first()
    latest_doc_stats = {
        'has_doc': False,
        'total_lines': 0,
        'lines_read': 0,
        'lines_error': 0,
        'last_line_read': None,
        'first_error_line': None,
        'doc_number': '',
        'supplier_name': '',
        'doc_type': ''
    }
    
    if latest_doc:
        summary = latest_doc.match_result.summary if hasattr(latest_doc, 'match_result') and latest_doc.match_result else {}
        
        # Get values with fallbacks for older documents without new fields
        total_lines = summary.get('total_lines_in_document', 0)
        lines_read = summary.get('lines_read_successfully', 0)
        
        # If old document doesn't have new fields, try to calculate from parsed_payload
        if total_lines == 0 and latest_doc.parsed_payload:
            total_lines = len(latest_doc.parsed_payload.get('lines', []))
            lines_ok = summary.get('lines_ok', 0)
            lines_read = lines_ok  # Use lines_ok as approximation for lines_read
        
        latest_doc_stats = {
            'has_doc': True,
            'total_lines': total_lines,
            'lines_read': lines_read,
            'lines_error': total_lines - lines_read if total_lines > 0 else 0,
            'last_line_read': summary.get('last_successful_line', lines_read if lines_read > 0 else None),
            'first_error_line': summary.get('first_error_line'),
            'doc_number': latest_doc.number,
            'supplier_name': latest_doc.supplier.name,
            'doc_type': latest_doc.get_doc_type_display()
        }

    ctx = {
        'total_docs': total_docs,
        'matched': matched,
        'exceptions': exceptions,
        'errors': errors,
        'pending': pending,
        'suppliers': suppliers,
        'latest': latest,
        'latest_doc_stats': latest_doc_stats,
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
