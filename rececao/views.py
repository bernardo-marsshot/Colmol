# views.py
from django.shortcuts import render, redirect, get_object_or_404
from django.db.models import Count
from .models import InboundDocument, Supplier, PurchaseOrder
from .forms import InboundUploadForm
from .services import process_inbound, export_document_to_excel

def dashboard(request):
    # Dashboard mostra apenas Guias de Remessa (GR), nao Notas de Encomenda (FT)
    guias_queryset = InboundDocument.objects.filter(doc_type='GR')
    
    # Contagens por estado (apenas Guias)
    total_docs = guias_queryset.count()
    matched    = guias_queryset.filter(match_result__status='matched').count()
    exceptions = guias_queryset.filter(match_result__status='exceptions').count()
    errors     = guias_queryset.filter(match_result__status='error').count()

    # Pendente = tudo o que não tem resultado ainda (ou qualquer outro estado não coberto acima)
    pending = total_docs - matched - exceptions - errors
    if pending < 0:
        pending = 0  # salvaguarda, caso existam estados “extra” ou inconsistências

    suppliers = Supplier.objects.count()

    latest_docs = (
        guias_queryset
        .select_related('supplier', 'po', 'match_result')
        .order_by('-received_at')
    )
    
    # Calculate reading percentage for each document
    latest = []
    for doc in latest_docs:
        # Calculate reading percentage
        summary = doc.match_result.summary if hasattr(doc, 'match_result') and doc.match_result else {}
        total_lines = summary.get('total_lines_in_document', 0)
        lines_read = summary.get('lines_read_successfully', 0)
        
        # Fallback for older documents
        if total_lines == 0 and doc.parsed_payload:
            total_lines = len(doc.parsed_payload.get('lines', []))
            lines_ok = summary.get('lines_ok', 0)
            lines_read = lines_ok
        
        # Calculate percentage
        reading_percentage = (lines_read / total_lines * 100) if total_lines > 0 else 0
        
        # Add percentage attribute to document
        doc.reading_percentage = round(reading_percentage, 1)
        latest.append(doc)
    
    # Get latest document statistics for line reading chart (apenas Guias)
    latest_doc = guias_queryset.select_related('supplier', 'po', 'match_result').order_by('-received_at').first()
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
    
    # Calculate line statistics for this document
    total_lines = inbound.lines.count()
    lines_with_errors = inbound.exceptions.values('line_ref').distinct().count()
    lines_read = total_lines - lines_with_errors
    
    line_stats = {
        'total_lines': total_lines,
        'lines_read': lines_read,
        'lines_error': lines_with_errors,
    }
    
    return render(request, 'inbound_detail.html', {
        'inbound': inbound, 
        'result': result,
        'line_stats': line_stats
    })

def po_list(request):
    pos = PurchaseOrder.objects.all().order_by('-id')
    return render(request, 'po_list.html', {'pos': pos})

def export_excel(request, pk):
    """Export document to Excel"""
    return export_document_to_excel(pk)
