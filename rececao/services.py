
import hashlib
import os
import re
from io import BytesIO
from PIL import Image
import PyPDF2
import pytesseract
from pdf2image import convert_from_path
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, PatternFill
from django.http import HttpResponse
from .models import InboundDocument, ReceiptLine, CodeMapping, MatchResult, ExceptionTask, POLine
from django.db import transaction

def real_ocr_extract(file_path: str):
    """Real OCR using local Tesseract - extracts data from actual documents"""
    
    text_content = ""
    file_ext = os.path.splitext(file_path)[1].lower()
    
    # Extract text based on file type
    if file_ext == '.pdf':
        text_content = extract_text_from_pdf(file_path)
    elif file_ext in ['.jpg', '.jpeg', '.png', '.tiff', '.bmp']:
        text_content = extract_text_from_image(file_path)
    
    if not text_content.strip():
        print("❌ No text extracted from document - OCR failed")
        return {
            "error": "OCR failed - no text extracted from document",
            "numero_requisicao": f"ERROR-{os.path.basename(file_path)}",
            "document_number": "",
            "po_number": "",
            "supplier_name": "",
            "delivery_date": "",
            "lines": [],
            "totals": {"total_lines": 0, "total_quantity": 0}
        }
    
    print(f"✅ OCR successful: {len(text_content)} characters extracted")
    # Parse Portuguese document
    return parse_portuguese_document(text_content)

def extract_text_from_pdf(file_path: str) -> str:
    """Extract text from PDF using both text extraction and OCR"""
    try:
        # First try direct text extraction
        with open(file_path, 'rb') as file:
            reader = PyPDF2.PdfReader(file)
            text = ""
            for page in reader.pages:
                page_text = page.extract_text()
                if page_text:  # Handle None returns
                    text += page_text + "\n"
        
        # If we got meaningful text, return it
        if text.strip() and len(text.strip()) > 50:
            print(f"✅ PDF text extraction successful: {len(text)} chars")
            return text.strip()
        
        # Otherwise, convert PDF to images and run OCR
        print("📄 PDF has no extractable text, converting to images for OCR...")
        return extract_text_from_pdf_with_ocr(file_path)
        
    except Exception as e:
        print(f"❌ Error extracting PDF text, falling back to OCR: {e}")
        # If text extraction fails, try OCR
        return extract_text_from_pdf_with_ocr(file_path)

def extract_text_from_pdf_with_ocr(file_path: str) -> str:
    """Convert PDF pages to images and extract text with Tesseract OCR"""
    try:
        # Convert PDF pages to images
        pages = convert_from_path(file_path, dpi=300, first_page=1, last_page=3)  # Limit to first 3 pages
        
        all_text = ""
        for i, page in enumerate(pages):
            print(f"🔍 Running OCR on page {i+1}...")
            
            # Run OCR on each page
            page_text = pytesseract.image_to_string(
                page, 
                config='--psm 6 -l por',  # Portuguese language
                lang='por'
            )
            
            if page_text.strip():
                all_text += f"\n--- Página {i+1} ---\n{page_text}\n"
                print(f"✅ Page {i+1}: {len(page_text)} characters extracted")
            else:
                print(f"⚠️ Page {i+1}: No text found")
        
        return all_text.strip()
        
    except Exception as e:
        print(f"❌ Error with PDF OCR: {e}")
        return ""

def extract_text_from_image(file_path: str) -> str:
    """Extract text using Tesseract OCR"""
    try:
        image = Image.open(file_path)
        text = pytesseract.image_to_string(image, config='--psm 6 -l por')
        return text.strip()
    except Exception as e:
        print(f"Error with OCR: {e}")
        return ""

def parse_portuguese_document(text: str):
    """Parse Portuguese delivery receipt into structured data"""
    lines = text.split('\n')
    
    result = {
        "numero_requisicao": "",
        "document_number": "",
        "po_number": "",
        "supplier_name": "",
        "delivery_date": "",
        "lines": [],
        "totals": {"total_lines": 0, "total_quantity": 0}
    }
    
    # Extract key info with regex patterns
    patterns = {
        'req': r'(?:req|requisição)\.?\s*n?[oº]?\s*:?\s*([A-Z0-9\-/]+)',
        'doc': r'(?:guia|gr|documento)\.?\s*n?[oº]?\s*:?\s*([A-Z0-9\-/]+)',
        'data': r'(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})',
        'fornecedor': r'(?:fornecedor|empresa)\.?\s*:?\s*([^\n]+)'
    }
    
    for line in lines:
        line_lower = line.lower().strip()
        
        # Extract requisition number
        req_match = re.search(patterns['req'], line_lower, re.IGNORECASE)
        if req_match and not result["numero_requisicao"]:
            result["numero_requisicao"] = req_match.group(1).upper()
        
        # Extract document number  
        doc_match = re.search(patterns['doc'], line_lower, re.IGNORECASE)
        if doc_match and not result["document_number"]:
            result["document_number"] = doc_match.group(1).upper()
            result["po_number"] = doc_match.group(1).upper() # For compatibility
        
        # Extract date
        date_match = re.search(patterns['data'], line)
        if date_match and not result["delivery_date"]:
            result["delivery_date"] = date_match.group(1)
        
        # Extract supplier
        supplier_match = re.search(patterns['fornecedor'], line_lower)
        if supplier_match and not result["supplier_name"]:
            result["supplier_name"] = supplier_match.group(1).title()
    
    # Extract product lines
    product_lines = extract_product_lines(text)
    
    # Convert to legacy format for compatibility
    legacy_lines = []
    for produto in product_lines:
        legacy_lines.append({
            "supplier_code": produto["codigo_fornecedor"],
            "description": produto["descricao"], 
            "unit": produto["unidade"],
            "qty": produto["quantidade"],
            "mini_codigo": produto["mini_codigo"],
            "dimensoes": produto["dimensoes"]
        })
    
    result["lines"] = legacy_lines
    result["totals"]["total_lines"] = len(legacy_lines)
    result["totals"]["total_quantity"] = sum(linha["qty"] for linha in legacy_lines)
    
    return result

def extract_product_lines(text: str):
    """Extract product lines from text"""
    lines = text.split('\n')
    products = []
    
    for line in lines:
        line_clean = line.strip()
        if len(line_clean) < 5:
            continue
            
        # Look for product patterns
        product_match = re.search(r'(BL[A-Z0-9\-]+|BLOCO[A-Z0-9\-\s]+|D\d+)', line, re.IGNORECASE)
        if product_match:
            produto = {
                "codigo_fornecedor": product_match.group(1),
                "descricao": line_clean,
                "dimensoes": {"comprimento": 0, "largura": 0, "espessura": 0},
                "quantidade": 0,
                "unidade": "UNI",
                "mini_codigo": ""
            }
            
            # Extract dimensions
            dim_match = re.search(r'(\d+)\s*x\s*(\d+)(?:\s*x\s*(\d+))?', line)
            if dim_match:
                try:
                    produto["dimensoes"]["largura"] = int(dim_match.group(1))
                    produto["dimensoes"]["comprimento"] = int(dim_match.group(2))
                    if dim_match.group(3):
                        produto["dimensoes"]["espessura"] = int(dim_match.group(3))
                except ValueError:
                    pass
            
            # Extract quantity
            qty_match = re.search(r'(\d+(?:[.,]\d+)?)\s*(?:un|uni|unidades)', line, re.IGNORECASE)
            if qty_match:
                try:
                    produto["quantidade"] = float(qty_match.group(1).replace(',', '.'))
                except ValueError:
                    produto["quantidade"] = 0
            
            # Generate mini código
            produto["mini_codigo"] = generate_mini_codigo(produto)
            products.append(produto)
    
    return products

def generate_mini_codigo(linha):
    """Generate Mini Código"""
    dimensoes = linha.get("dimensoes", {})
    codigo = linha.get("codigo_fornecedor", "")
    
    comp = dimensoes.get("comprimento", 0)
    larg = dimensoes.get("largura", 0)
    esp = dimensoes.get("espessura", 0)
    
    # Extract density if present
    densidade_match = re.search(r'(D\d+)', codigo)
    densidade = densidade_match.group(1) if densidade_match else ""
    
    if all([comp, larg, esp]) and densidade:
        return f"{densidade}-{larg}x{comp}x{esp}"
    elif all([comp, larg, esp]):
        return f"{larg}x{comp}x{esp}"
    else:
        return codigo

def get_realistic_fallback():
    """Realistic fallback data when OCR fails"""
    return {
        "numero_requisicao": "REQ-2025-0045",
        "document_number": "GR-2025-0234",
        "po_number": "GR-2025-0234", 
        "supplier_name": "Blocos Portugal SA",
        "delivery_date": "25/09/2025",
        "lines": [
            {
                "supplier_code": "BLC-D25-200x300x150",
                "description": "Bloco betão celular D25 200x300x150",
                "unit": "UNI",
                "qty": 48,
                "mini_codigo": "D25-200x300x150",
                "dimensoes": {"comprimento": 300, "largura": 200, "espessura": 150}
            },
            {
                "supplier_code": "BLC-D30-200x600x200", 
                "description": "Bloco betão celular D30 200x600x200",
                "unit": "UNI",
                "qty": 24,
                "mini_codigo": "D30-200x600x200",
                "dimensoes": {"comprimento": 600, "largura": 200, "espessura": 200}
            }
        ],
        "totals": {"total_lines": 2, "total_quantity": 72}
    }

def map_supplier_codes(supplier, payload):
    mapped = []
    for l in payload.get("lines", []):
        supplier_code = l.get("supplier_code")
        mapping = CodeMapping.objects.filter(supplier=supplier, supplier_code=supplier_code).first()
        mapped.append({
            **l,
            "internal_sku": mapping.internal_sku if mapping else None,
            "confidence": mapping.confidence if mapping else 0.0
        })
    return mapped

@transaction.atomic
def process_inbound(inbound: InboundDocument):
    # Extract using real OCR
    payload = real_ocr_extract(inbound.file.path)
    
    # Check if OCR failed
    if payload.get("error"):
        print(f"❌ OCR failed for document {inbound.id}: {payload['error']}")
        # Create exception task for OCR failure
        ExceptionTask.objects.create(
            inbound=inbound, 
            line_ref="OCR", 
            issue=f"OCR extraction failed: {payload['error']}"
        )
    
    inbound.parsed_payload = payload
    inbound.save()

    # Create receipt lines
    inbound.lines.all().delete()
    mapped_lines = map_supplier_codes(inbound.supplier, payload)
    for ml in mapped_lines:
        ReceiptLine.objects.create(
            inbound=inbound,
            supplier_code=ml["supplier_code"],
            maybe_internal_sku=ml.get("internal_sku") or "",
            description=ml.get("description",""),
            unit=ml.get("unit","UN"),
            qty_received=ml.get("qty",0)
        )

    # Try to link to PO by number
    from .models import PurchaseOrder
    po = PurchaseOrder.objects.filter(number=payload.get("po_number")).first()
    if po:
        inbound.po = po
        inbound.save()

    # Matching rules: compare receipt vs PO lines
    ok = 0; issues = 0; exceptions = []
    if inbound.po:
        for r in inbound.lines.all():
            pol = None
            if r.maybe_internal_sku:
                pol = POLine.objects.filter(po=inbound.po, internal_sku=r.maybe_internal_sku).first()
            # If we don't have mapping, raise exception
            if not pol:
                issues += 1
                exceptions.append({"line": r.supplier_code, "issue":"Código não mapeado para SKU interno", "suggested": ""})
                continue
            # quantity check with tolerance
            diff = float(r.qty_received) - float(pol.qty_ordered)
            if abs(diff) > float(pol.tolerance):
                issues += 1
                exceptions.append({"line": r.maybe_internal_sku, "issue": f"Quantidade divergente (recebida {r.qty_received} vs pedida {pol.qty_ordered} ± tol {pol.tolerance})"})
            else:
                ok += 1
    else:
        # No PO linked, all lines become exceptions
        for r in inbound.lines.all():
            issues += 1
            exceptions.append({"line": r.supplier_code, "issue": "PO não identificado no documento"})

    # Persist match result
    import uuid, json
    res, _ = MatchResult.objects.get_or_create(inbound=inbound)
    
    # Calculate line statistics for the chart
    total_lines_in_doc = len(payload.get("lines", []))
    lines_read_successfully = ok
    first_error_line = None
    
    # Find first error line number
    if exceptions:
        # Try to find the line number in the document
        for idx, line in enumerate(payload.get("lines", []), 1):
            line_code = line.get("supplier_code", "")
            if any(line_code in ex.get("line", "") for ex in exceptions):
                first_error_line = idx
                break
    
    res.status = 'matched' if issues == 0 else 'exceptions'
    res.summary = {
        "lines_ok": ok, 
        "lines_issues": issues,
        "total_lines_in_document": total_lines_in_doc,
        "lines_read_successfully": lines_read_successfully,
        "first_error_line": first_error_line,
        "last_successful_line": lines_read_successfully if lines_read_successfully > 0 else None
    }
    res.certified_id = hashlib.sha256((str(inbound.id)+str(payload)).encode()).hexdigest()[:16]
    res.save()

    # Store exception tasks
    inbound.exceptions.all().delete()
    for ex in exceptions:
        ExceptionTask.objects.create(inbound=inbound, line_ref=ex["line"], issue=ex["issue"])
    return res

def export_document_to_excel(inbound_id: int) -> HttpResponse:
    """Export document data to Excel format"""
    try:
        inbound = InboundDocument.objects.get(id=inbound_id)
        
        # Create workbook
        wb = Workbook()
        ws = wb.active
        ws.title = "Requisição Processada"
        
        # Headers
        headers = ["Nº Requisição", "Mini Código", "Dimensões (LxCxE)", "Quantidade", "Código Fornecedor", "Descrição"]
        
        # Style headers
        header_font = Font(bold=True, color="FFFFFF")
        header_fill = PatternFill(start_color="FF6B35", end_color="FF6B35", fill_type="solid")
        
        for col, header in enumerate(headers, 1):
            cell = ws.cell(row=1, column=col, value=header)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = Alignment(horizontal="center")
        
        # Data rows
        numero_req = inbound.parsed_payload.get("numero_requisicao", "") or f"REQ-{inbound.id}"
        
        for row, linha in enumerate(inbound.lines.all(), 2):
            # Get real dimensions from parsed payload, not internal SKU
            dimensoes = ""
            
            # Extract actual dimensions from parsed payload
            for payload_line in inbound.parsed_payload.get("lines", []):
                if payload_line.get("supplier_code") == linha.supplier_code:
                    dims = payload_line.get("dimensoes", {})
                    if dims and any(dims.values()):
                        larg = dims.get('largura', 0)
                        comp = dims.get('comprimento', 0) 
                        esp = dims.get('espessura', 0)
                        if larg and comp and esp:
                            dimensoes = f"{larg}x{comp}x{esp}"
                        elif larg and comp:
                            dimensoes = f"{larg}x{comp}"
                    break
            
            # If no dimensions found, leave empty (don't use internal SKU)
            if not dimensoes:
                dimensoes = ""
            
            mini_codigo = ""
            # Extract mini código from parsed payload
            for payload_line in inbound.parsed_payload.get("lines", []):
                if payload_line.get("supplier_code") == linha.supplier_code:
                    mini_codigo = payload_line.get("mini_codigo", "")
                    break
            
            ws.cell(row=row, column=1, value=numero_req)
            ws.cell(row=row, column=2, value=mini_codigo or linha.maybe_internal_sku)
            ws.cell(row=row, column=3, value=dimensoes)
            ws.cell(row=row, column=4, value=float(linha.qty_received))
            ws.cell(row=row, column=5, value=linha.supplier_code)
            ws.cell(row=row, column=6, value=linha.description)
        
        # Auto-adjust column widths
        for column in ws.columns:
            max_length = 0
            column_letter = column[0].column_letter
            for cell in column:
                try:
                    if len(str(cell.value)) > max_length:
                        max_length = len(str(cell.value))
                except:
                    pass
            adjusted_width = min(max_length + 2, 50)
            ws.column_dimensions[column_letter].width = adjusted_width
        
        # Create response
        response = HttpResponse(
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        response['Content-Disposition'] = f'attachment; filename="requisicao_{numero_req}_{inbound.id}.xlsx"'
        
        wb.save(response)
        return response
        
    except Exception as e:
        print(f"Error exporting to Excel: {e}")
        raise
