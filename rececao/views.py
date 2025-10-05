# views.py
from django.shortcuts import render, redirect, get_object_or_404
from django.db.models import Count
from .models import InboundDocument, Supplier, PurchaseOrder
from .forms import InboundUploadForm
from .services import process_inbound, export_document_to_excel

def dashboard(request):
    # Estados (nota: services.py usa 'matched' e 'exceptions' (plural))
    total_docs = InboundDocument.objects.count()
    matched    = InboundDocument.objects.filter(match_result__status='matched').count()
    exceptions = InboundDocument.objects.filter(match_result__status='exceptions').count()
    errors     = InboundDocument.objects.filter(match_result__status='error').count()  # se implementado
    computed   = matched + exceptions + errors
    pending    = max(total_docs - computed, 0)

    suppliers = Supplier.objects.count()

    latest_docs_qs = (
        InboundDocument.objects
        .select_related('supplier', 'po', 'match_result')
        .order_by('-received_at')[:10]
    )

    # enriquecer com % leitura
    latest = []
    for doc in latest_docs_qs:
        summary = getattr(getattr(doc, 'match_result', None), 'summary', {}) or {}
        total_lines = summary.get('total_lines_in_document', 0)
        lines_read  = summary.get('lines_read_successfully', 0)

        # fallback para docs antigos
        if total_lines == 0 and doc.parsed_payload:
            total_lines = len(doc.parsed_payload.get('lines', []))
            lines_read = summary.get('lines_ok', 0)

        reading_percentage = (lines_read / total_lines * 100) if total_lines > 0 else 0
        doc.reading_percentage = round(reading_percentage, 1)
        latest.append(doc)

    # estatísticas do documento mais recente (para 2.º gráfico)
    latest_doc = (
        InboundDocument.objects
        .select_related('supplier', 'po', 'match_result')
        .order_by('-received_at')
        .first()
    )

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
        summary = getattr(getattr(latest_doc, 'match_result', None), 'summary', {}) or {}
        total_lines = summary.get('total_lines_in_document', 0)
        lines_read  = summary.get('lines_read_successfully', 0)

        # fallback p/ docs antigos
        if total_lines == 0 and latest_doc.parsed_payload:
            total_lines = len(latest_doc.parsed_payload.get('lines', []))
            lines_read = summary.get('lines_ok', 0)

        latest_doc_stats = {
            'has_doc': True,
            'total_lines': total_lines,
            'lines_read': lines_read,
            'lines_error': max(total_lines - lines_read, 0) if total_lines else 0,
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
