# rececao/services.py  (VERSÃO SEM PDFPLUMBER)
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
from django.db import transaction

from .models import (
    InboundDocument, ReceiptLine, CodeMapping, MatchResult, ExceptionTask, POLine,
    PurchaseOrder
)

# (Opcional) caminho do Tesseract no Windows:
# pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

# ----------------- Helpers PT -----------------

def normalize_qty_pt(s: str) -> float:
    """34,00 -> 34.0 | 1.234,50 -> 1234.5 | 5,000 -> 5.0"""
    if s is None:
        return 0.0
    s = str(s).replace('\u00A0', ' ').strip()
    # remove pontos de milhar apenas quando seguidos de 3 dígitos
    s = re.sub(r'\.(?=\d{3}\b)', '', s)
    # troca vírgula decimal por ponto
    s = s.replace(',', '.')
    try:
        return float(s)
    except Exception:
        return 0.0

def normalize_money_pt(s: str) -> float:
    if s is None:
        return 0.0
    s = re.sub(r'[^\d,.-]', '', str(s))
    return normalize_qty_pt(s)

# ----------------- OCR / Leitura de PDF -----------------

def extract_text_from_pdf(file_path: str) -> str:
    """Extrai texto de um PDF: tenta PyPDF2; se falhar/for insuficiente, cai para OCR."""
    try:
        with open(file_path, 'rb') as file:
            reader = PyPDF2.PdfReader(file)
            text = ""
            for page in reader.pages:
                page_text = page.extract_text() or ""
                text += page_text + "\n"
        if text and len(text.strip()) > 50:
            print(f"✅ PyPDF2 extraiu {len(text)} caracteres.")
            return text.strip()
        else:
            print("📄 PyPDF2 devolveu pouco texto. A usar OCR…")
    except Exception as e:
        print(f"⚠️ Erro PyPDF2: {e} — a usar OCR…")

    # Fallback: OCR completo (PDF → imagens)
    return extract_text_from_pdf_with_ocr(file_path)

def extract_text_from_pdf_with_ocr(file_path: str) -> str:
    """Converte todas as páginas do PDF em imagens e corre Tesseract OCR."""
    try:
        print("📷 A converter PDF para imagens (OCR em todas as páginas)…")
        pages = convert_from_path(file_path, dpi=300)
        all_text = ""
        for i, page in enumerate(pages, 1):
            print(f"🔍 OCR página {i}/{len(pages)}…")
            ocr_text = pytesseract.image_to_string(page, lang='por', config='--psm 6')
            all_text += f"\n--- Página {i} ---\n{ocr_text}\n"
        print(f"✅ OCR terminou ({len(all_text)} caracteres).")
        return all_text.strip()
    except Exception as e:
        print(f"❌ Erro no OCR: {e}")
        return ""

def extract_text_from_image(file_path: str) -> str:
    """OCR para imagem (JPG/PNG/TIFF/BMP)."""
    try:
        image = Image.open(file_path)
        ocr_text = pytesseract.image_to_string(image, lang='por', config='--psm 6')
        return ocr_text.strip()
    except Exception as e:
        print(f"❌ OCR imagem erro: {e}")
        return ""

# ----------------- Parse (cabeçalho + linhas + totais) a partir de TEXTO -----------------

# filtros de ruído para não confundir moradas/IBAN com linhas de item
NOISE_KEYWORDS = [
    'iban','nib','morada','endereço','endereco','address',
    'página','pagina','guia de remessa','nota de encomenda',
    'doc','documento','telefone','telemóvel','email','e-mail',
    'contribuinte','nif','código postal','zona industrial',
    'código do cliente','cliente','fornecedor:'
]
NOISE_REGEXES = [
    r'^\s*(p(á|a)gina)\s*\d+/?\d+\s*$',
    r'^\s*\d{2}[/-]\d{2}[/-]\d{2,4}\s*$',
    r'^\s*(n[ºo]\s*)?\d{6,}\s*$',
]

def is_noise_line(s: str) -> bool:
    low = (s or "").lower()
    if len(low) < 3:
        return True
    if any(kw in low for kw in NOISE_KEYWORDS):
        return True
    if any(re.search(rx, low, re.IGNORECASE) for rx in NOISE_REGEXES):
        return True
    # muitas palavras e sem números → provável morada/texto corrido
    if not re.search(r'\d', low) and len(low.split()) >= 6:
        return True
    return False

def extract_product_lines(text: str):
    """
    Foco: CÓDIGO FORNECEDOR (início da linha) + DESCRIÇÃO + QUANTIDADE (fim da linha).
    Ex.: "CWH 1ECWH Nº 10955/25EU de 05-09-2025 .... 5,000"
    """
    products = []
    for raw in text.split('\n'):
        line = ' '.join((raw or '').strip().split())  # normaliza espaços
        if len(line) < 4:
            continue
        if is_noise_line(line):
            continue

        # Código no INÍCIO (INA | CWH | U/N. | ADA | T50, etc.)
        code_rx = r'^\s*(?P<code>[A-Z]{2,6}(?:[./-][A-Z0-9]{1,4})?)\b'
        m_code = re.search(code_rx, line)
        if not m_code:
            continue

        # Quantidade no FIM (5 | 5,0 | 5,000 | 1.234,50) com/sem "un/uni/unidades"
        qty_rx = r'(?P<qty>\d{1,3}(?:[\.\s]?\d{3})*(?:,\d+)?|\d+(?:,\d+)?)(?:\s*(?:un|uni|unid|unidades))?\s*$'
        m_qty = re.search(qty_rx, line, flags=re.IGNORECASE)
        if not m_qty:
            continue

        code = m_code.group('code').upper()
        qty  = normalize_qty_pt(m_qty.group('qty'))

        # descrição = tudo entre o código e a quantidade
        start_desc = m_code.end()
        end_desc   = m_qty.start()
        desc = line[start_desc:end_desc].strip(' -–:;')

        # segurança extra contra moradas/cabeçalhos
        if is_noise_line(desc):
            continue

        produto = {
            "codigo_fornecedor": code,
            "descricao": desc if desc else code,
            "dimensoes": {"comprimento": 0, "largura": 0, "espessura": 0},
            "quantidade": qty,
            "unidade": "UNI",
            "mini_codigo": ""
        }
        products.append(produto)

    return products

def parse_portuguese_document(text: str):
    """Extrai header (doc/po/data/fornecedor), LINHAS e TOTAIS a partir do texto plano."""
    result = {
        "numero_requisicao": "",
        "document_number": "",
        "po_number": "",
        "supplier_name": "",
        "delivery_date": "",
        "lines": [],
        "totals": {"total_lines": 0, "total_quantity": 0},
        # secção financeira heurística (se existir no texto)
        "finance": {"total_mercadoria": None, "iva": None, "total_eur": None}
    }

    lines = text.split('\n')

    # Cabeçalho (heurísticas tolerantes)
    patterns = {
        "req": r"(?:req|requisição)\.?\s*n?[oº]?\s*:?\s*([A-Z0-9\-/]+)",
        "doc": r"(?:guia|gr|documento)\.?\s*n?[oº]?\s*:?\s*([A-Z0-9\-/]+)",
        "data": r"(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})",
        "forn": r"(?:fornecedor|supplier|empresa)\.?\s*:?\s*([^\n]+)"
    }

    for ln in lines:
        low = ln.lower().strip()
        if not result["numero_requisicao"]:
            m = re.search(patterns["req"], low, re.IGNORECASE)
            if m: result["numero_requisicao"] = m.group(1).upper()
        if not result["document_number"]:
            m = re.search(patterns["doc"], low, re.IGNORECASE)
            if m:
                result["document_number"] = m.group(1).upper()
                result["po_number"] = result["document_number"]
        if not result["delivery_date"]:
            m = re.search(patterns["data"], ln)
            if m: result["delivery_date"] = m.group(1)
        if not result["supplier_name"]:
            m = re.search(patterns["forn"], low)
            if m: result["supplier_name"] = m.group(1).strip().title()

    # Linhas de item (texto)
    product_lines = extract_product_lines(text)

    legacy_lines = []
    for p in product_lines:
        legacy_lines.append({
            "supplier_code": p["codigo_fornecedor"],
            "description": p["descricao"],
            "unit": p["unidade"],
            "qty": p["quantidade"],
            "mini_codigo": p["mini_codigo"],
            "dimensoes": p["dimensoes"]
        })

    result["lines"] = legacy_lines
    result["totals"]["total_lines"] = len(legacy_lines)
    result["totals"]["total_quantity"] = sum(x["qty"] for x in legacy_lines)

    # Totais (se existirem no texto — heurísticas)
    full_text = "\n".join(lines)
    def find_money(label_regex):
        m = re.search(rf'{label_regex}\s+([0-9\.\s]*,\d{{2}}|\d+)', full_text, re.IGNORECASE)
        return normalize_money_pt(m.group(1)) if m else None

    result["finance"]["total_mercadoria"] = find_money(r'Total\s+Mercadoria')
    result["finance"]["iva"] = find_money(r'IVA|Iva')
    m_total = re.search(r'Total\s*\(EUR\)\s+([0-9\.\s]*,\d{2}|\d+)', full_text, re.IGNORECASE)
    if m_total:
        result["finance"]["total_eur"] = normalize_money_pt(m_total.group(1))

    return result

# ----------------- Orquestração -----------------

def real_ocr_extract(file_path: str):
    """1) PyPDF2 → texto; 2) OCR fallback; 3) Parse textual."""
    ext = os.path.splitext(file_path)[1].lower()
    if ext == ".pdf":
        text_content = extract_text_from_pdf(file_path)
    elif ext in [".jpg", ".jpeg", ".png", ".tiff", ".bmp"]:
        text_content = extract_text_from_image(file_path)
    else:
        text_content = ""

    # Log de debug (primeiras linhas)
    preview = "\n".join(text_content.splitlines()[:60])
    print("---- PREVIEW TEXTO ----\n" + preview + "\n-----------------------")

    if not text_content.strip():
        return {
            "error": "OCR failed - no text extracted from document",
            "numero_requisicao": f"ERROR-{os.path.basename(file_path)}",
            "document_number": "", "po_number": "",
            "supplier_name": "", "delivery_date": "",
            "lines": [], "totals": {"total_lines": 0, "total_quantity": 0},
            "finance": {"total_mercadoria": None, "iva": None, "total_eur": None}
        }

    return parse_portuguese_document(text_content)

# ----------------- Mapping / Matching / Export -----------------

def map_supplier_codes(supplier, payload):
    mapped = []
    for l in payload.get("lines", []):
        supplier_code = l.get("supplier_code")
        mapping = CodeMapping.objects.filter(supplier=supplier, supplier_code=supplier_code).first()
        mapped.append({
            **l,
            "internal_sku": (mapping.internal_sku if mapping else None),
            "confidence": (mapping.confidence if mapping else 0.0),
        })
    return mapped

@transaction.atomic
def process_inbound(inbound: InboundDocument):
    payload = real_ocr_extract(inbound.file.path)

    if payload.get("error"):
        ExceptionTask.objects.create(
            inbound=inbound, line_ref="OCR",
            issue=f"OCR extraction failed: {payload['error']}"
        )

    inbound.parsed_payload = payload
    inbound.save()

    # recria ReceiptLines
    inbound.lines.all().delete()
    mapped_lines = map_supplier_codes(inbound.supplier, payload)
    for ml in mapped_lines:
        ReceiptLine.objects.create(
            inbound=inbound,
            supplier_code=ml["supplier_code"],
            maybe_internal_sku=ml.get("internal_sku") or "",
            description=ml.get("description", ""),
            unit=ml.get("unit", "UN"),
            qty_received=ml.get("qty", 0),
        )

    # tenta ligar à PO
    po = PurchaseOrder.objects.filter(number=payload.get("po_number")).first()
    if po:
        inbound.po = po
        inbound.save()

    # Matching
    ok = 0; issues = 0; exceptions = []
    if inbound.po:
        for r in inbound.lines.all():
            pol = None
            if r.maybe_internal_sku:
                pol = POLine.objects.filter(po=inbound.po, internal_sku=r.maybe_internal_sku).first()
            if not pol:
                issues += 1
                exceptions.append({"line": r.supplier_code, "issue": "Código não mapeado para SKU interno"})
                continue
            diff = float(r.qty_received) - float(pol.qty_ordered)
            if abs(diff) > float(pol.tolerance):
                issues += 1
                exceptions.append({
                    "line": r.maybe_internal_sku,
                    "issue": f"Quantidade divergente (recebida {r.qty_received} vs pedida {pol.qty_ordered} ± tol {pol.tolerance})"
                })
            else:
                ok += 1
    else:
        for r in inbound.lines.all():
            issues += 1
            exceptions.append({"line": r.supplier_code, "issue": "PO não identificada"})

    res, _ = MatchResult.objects.get_or_create(inbound=inbound)
    total_lines_in_doc = len(payload.get("lines", []))
    lines_read_successfully = ok
    first_error_line = None
    if exceptions:
        for idx, line in enumerate(payload.get("lines", []), 1):
            code = line.get("supplier_code", "")
            if any(code in ex.get("line", "") for ex in exceptions):
                first_error_line = idx
                break

    res.status = "matched" if issues == 0 else "exceptions"
    res.summary = {
        "lines_ok": ok,
        "lines_issues": issues,
        "total_lines_in_document": total_lines_in_doc,
        "lines_read_successfully": lines_read_successfully,
        "first_error_line": first_error_line,
        "last_successful_line": (lines_read_successfully or None),
    }
    res.certified_id = hashlib.sha256((str(inbound.id)+str(payload)).encode()).hexdigest()[:16]
    res.save()

    inbound.exceptions.all().delete()
    for ex in exceptions:
        ExceptionTask.objects.create(inbound=inbound, line_ref=ex["line"], issue=ex["issue"])
    return res

def export_document_to_excel(inbound_id: int) -> HttpResponse:
    """Exporta: Nº Requisição, Mini Código, Dimensões, Quantidade, Código Fornecedor, Descrição."""
    inbound = InboundDocument.objects.get(id=inbound_id)

    wb = Workbook()
    ws = wb.active
    ws.title = "Requisição Processada"

    headers = ["Nº Requisição", "Mini Código", "Dimensões (LxCxE)", "Quantidade", "Código Fornecedor", "Descrição"]
    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="FF6B35", end_color="FF6B35", fill_type="solid")

    for col, header in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=header)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center")

    numero_req = inbound.parsed_payload.get("numero_requisicao", "") or f"REQ-{inbound.id}"

    for row, linha in enumerate(inbound.lines.all(), 2):
        dimensoes = ""
        mini_codigo = ""
        for payload_line in inbound.parsed_payload.get("lines", []):
            if payload_line.get("supplier_code") == linha.supplier_code:
                dims = payload_line.get("dimensoes", {})
                if dims and any(dims.values()):
                    larg = dims.get('largura', 0)
                    comp = dims.get('comprimento', 0)
                    esp  = dims.get('espessura', 0)
                    if larg and comp and esp:
                        dimensoes = f"{larg}x{comp}x{esp}"
                    elif larg and comp:
                        dimensoes = f"{larg}x{comp}"
                mini_codigo = payload_line.get("mini_codigo", "")
                break

        ws.cell(row=row, column=1, value=numero_req)
        ws.cell(row=row, column=2, value=mini_codigo or linha.maybe_internal_sku)
        ws.cell(row=row, column=3, value=dimensoes)
        ws.cell(row=row, column=4, value=float(linha.qty_received))
        ws.cell(row=row, column=5, value=linha.supplier_code)
        ws.cell(row=row, column=6, value=linha.description)

    # Ajuste automático de largura
    for column in ws.columns:
        max_length = 0
        letter = column[0].column_letter
        for cell in column:
            try:
                max_length = max(max_length, len(str(cell.value)))
            except Exception:
                pass
        ws.column_dimensions[letter].width = min(max_length + 2, 50)

    response = HttpResponse(
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = f'attachment; filename="requisicao_{numero_req}_{inbound.id}.xlsx"'
    wb.save(response)
    return response
