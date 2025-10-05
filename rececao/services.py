# rececao/services.py
import hashlib
import json
import os
import re
from io import BytesIO
from PIL import Image

import PyPDF2
import pytesseract
from pdf2image import convert_from_path
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, PatternFill

from django.conf import settings
from django.http import HttpResponse
from django.db import transaction

from .models import (InboundDocument, ReceiptLine, CodeMapping, MatchResult,
                     ExceptionTask, POLine, PurchaseOrder)

# --- QR opcional (requer lib de sistema zbar) ---
try:
    from pyzbar.pyzbar import decode
    import cv2
    import numpy as np
    QR_CODE_ENABLED = True
except ImportError:
    QR_CODE_ENABLED = False
    print("⚠️ QR code não disponível (instale zbar para ativar).")

# Se precisares especificar o caminho do tesseract no Windows:
# pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

# ----------------- OCR: PDF/Imagens -----------------


def save_extraction_to_json(data: dict, filename: str = "extracao.json"):
    """Salva os dados extraídos em um arquivo JSON."""
    try:
        json_path = os.path.join(settings.BASE_DIR, filename)
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"✅ Dados salvos em {json_path}")
        return json_path
    except Exception as e:
        print(f"❌ Erro ao salvar JSON: {e}")
        return None


def real_ocr_extract(file_path: str):
    """OCR real (Tesseract). Extrai texto e faz parse para estrutura."""
    text_content = ""
    ext = os.path.splitext(file_path)[1].lower()

    if ext == ".pdf":
        text_content = extract_text_from_pdf(file_path)
    elif ext in [".jpg", ".jpeg", ".png", ".tiff", ".bmp"]:
        text_content = extract_text_from_image(file_path)

    # Pré-visualização (debug) para validação
    preview = "\n".join(text_content.splitlines()[:60])
    print("---- OCR PREVIEW (primeiras linhas) ----")
    print(preview)
    print("----------------------------------------")

    if not text_content.strip():
        print("❌ OCR vazio")
        error_result = {
            "error": "OCR failed - no text extracted from document",
            "numero_requisicao": f"ERROR-{os.path.basename(file_path)}",
            "document_number": "",
            "po_number": "",
            "supplier_name": "",
            "delivery_date": "",
            "lines": [],
            "totals": {
                "total_lines": 0,
                "total_quantity": 0
            },
        }
        save_extraction_to_json(error_result)
        return error_result

    result = parse_portuguese_document(text_content)
    save_extraction_to_json(result)
    return result


def extract_text_from_pdf(file_path: str) -> str:
    """Tenta extrair texto (texto embutido). Se falhar, usa OCR página a página."""
    try:
        text = ""
        with open(file_path, "rb") as f:
            reader = PyPDF2.PdfReader(f)
            for page in reader.pages:
                page_text = page.extract_text() or ""
                text += page_text + "\n"

        if text.strip() and len(text.strip()) > 50:
            print(f"✅ PDF text extraction: {len(text)} chars")
            return text.strip()

        print("📄 PDF sem texto embutido—usar OCR…")
        return extract_text_from_pdf_with_ocr(file_path)

    except Exception as e:
        print(f"❌ Erro no extract_text_from_pdf: {e}")
        return extract_text_from_pdf_with_ocr(file_path)


def detect_and_read_qrcodes(image) -> str:
    """Lê QR codes (se disponível)."""
    if not QR_CODE_ENABLED:
        return ""

    try:
        arr = np.array(image)
        if len(arr.shape) == 3:
            arr = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
        qr_codes = decode(arr)
        out = ""
        for qr in qr_codes or []:
            data = qr.data.decode("utf-8")
            print(f"✅ QR: {data[:80]}…")
            out += f"\n[QR CODE]: {data}\n"
        return out
    except Exception as e:
        print(f"⚠️ QR erro: {e}")
        return ""


def extract_text_from_pdf_with_ocr(file_path: str) -> str:
    """Converte todas as páginas para imagem e aplica Tesseract."""
    try:
        print("📄 Converter PDF → imagens (OCR)…")
        pages = convert_from_path(file_path, dpi=300)
        all_text = ""
        for i, page in enumerate(pages, 1):
            print(f"🔍 Página {i}/{len(pages)}")
            all_text += detect_and_read_qrcodes(page)
            page_text = pytesseract.image_to_string(
                page, config="--psm 6 --oem 3 -l por", lang="por")
            if page_text.strip():
                all_text += f"\n--- Página {i} ---\n{page_text}\n"
        print(f"✅ OCR completo: {len(pages)} páginas")
        return all_text.strip()
    except Exception as e:
        print(f"❌ OCR PDF erro: {e}")
        return ""


def extract_text_from_image(file_path: str) -> str:
    """OCR para imagem ( + leitura de QR)."""
    try:
        img = Image.open(file_path)
        qr_text = detect_and_read_qrcodes(img)
        ocr_text = pytesseract.image_to_string(img,
                                               config="--psm 6 --oem 3 -l por",
                                               lang="por")
        return (qr_text + "\n" +
                ocr_text).strip() if qr_text else ocr_text.strip()
    except Exception as e:
        print(f"❌ OCR imagem erro: {e}")
        return ""


# ----------------- PARSE: heurísticas PT -----------------


def parse_portuguese_document(text: str):
    """Extrai cabeçalho (req/doc/fornecedor/data) e linhas de produto."""
    lines = text.split("\n")
    result = {
        "numero_requisicao": "",
        "document_number": "",
        "po_number": "",
        "supplier_name": "",
        "delivery_date": "",
        "lines": [],
        "totals": {
            "total_lines": 0,
            "total_quantity": 0
        },
    }

    patterns = {
        "req": r"(?:req|requisição)\.?\s*n?[oº]?\s*:?\s*([A-Z0-9\-/]+)",
        "doc": r"(?:guia|gr|documento)\.?\s*n?[oº]?\s*:?\s*([A-Z0-9\-/]+)",
        "data": r"(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})",
        "fornecedor": r"(?:fornecedor|empresa)\.?\s*:?\s*([^\n]+)",
    }

    for ln in lines:
        low = ln.lower().strip()

        if not result["numero_requisicao"]:
            m = re.search(patterns["req"], low, re.IGNORECASE)
            if m:
                result["numero_requisicao"] = m.group(1).upper()

        if not result["document_number"]:
            m = re.search(patterns["doc"], low, re.IGNORECASE)
            if m:
                result["document_number"] = m.group(1).upper()
                result["po_number"] = result["document_number"]

        if not result["delivery_date"]:
            m = re.search(patterns["data"], ln)
            if m:
                result["delivery_date"] = m.group(1)

        if not result["supplier_name"]:
            m = re.search(patterns["fornecedor"], low)
            if m:
                result["supplier_name"] = m.group(1).title()

    product_lines = extract_product_lines(text)

    legacy = []
    for p in product_lines:
        legacy.append({
            "supplier_code": p["codigo_fornecedor"],
            "description": p["descricao"],
            "linha_raw": p["linha_raw"],
            "unit": p["unidade"],
            "qty": p["quantidade"],
            "mini_codigo": p["mini_codigo"],
            "dimensoes": p["dimensoes"],
        })

    result["lines"] = legacy
    result["totals"]["total_lines"] = len(legacy)
    result["totals"]["total_quantity"] = sum(x["qty"] for x in legacy)
    return result


def extract_product_lines(text: str):
    """Extrai linhas de produto com regex tolerante a formatos reais."""
    products = []
    lines = text.split("\n")

    code_pat = r"(?P<code>(?:[A-Z]{1}[A-Z0-9\-\/\.]{2,}))"  # BLC-D25-200x300, REF-123, etc.
    dens_pat = r"(?P<densidade>D\d{2})?"  # D23, D30, etc. (opcional)
    sep = r"[xX×\- ]"  # separadores
    dim_pat = rf"(?P<dim>(\d{{2,4}}){sep}(\d{{2,4}})(?:{sep}(\d{{2,4}}))?)"
    qty_pat = r"(?P<qty>\d+(?:[.,]\d+)?)\s*(?:un|uni|unid|unidades)?$"

    line_regex = re.compile(
        rf"(?i)^(?=.*{code_pat})(?=.*{dim_pat}).*{qty_pat}")

    for raw in lines:
        line = raw.strip()
        if len(line) < 5:
            continue

        m = line_regex.search(line)
        if not m:
            # Fallback: ordem trocada; procurar blocos na linha
            code_m = re.search(code_pat, line)
            dim_m = re.search(dim_pat, line)
            qty_m = re.search(qty_pat, line, flags=re.IGNORECASE)
            if not (code_m and qty_m and dim_m):
                continue
            m_code = code_m.group("code")
            m_qty = qty_m.group("qty")
            m_dim = dim_m.group("dim")
            dims_nums = re.split(sep, m_dim)
        else:
            m_code = m.group("code")
            m_qty = m.group("qty")
            m_dim = m.group("dim")
            dims_nums = re.split(sep, m_dim)

        # quantidade
        try:
            qty = float(m_qty.replace(",", "."))
        except Exception:
            qty = 0.0

        # dimensões
        larg = comp = esp = 0
        try:
            if len(dims_nums) >= 2:
                larg = int(dims_nums[0])
                comp = int(dims_nums[1])
                if len(dims_nums) >= 3 and dims_nums[2].isdigit():
                    esp = int(dims_nums[2])
        except Exception:
            pass

        # densidade (se houver)
        densidade = ""
        dm = re.search(r"(D\d{2})", line, flags=re.IGNORECASE)
        if dm:
            densidade = dm.group(1).upper()

        produto = {
            "codigo_fornecedor": m_code.upper(),
            "descricao": line,
            "linha_raw": raw,
            "dimensoes": {
                "comprimento": comp,
                "largura": larg,
                "espessura": esp
            },
            "quantidade": qty,
            "unidade": "UNI",
            "mini_codigo": "",  # calculado já de seguida
        }
        produto["mini_codigo"] = generate_mini_codigo(produto)
        products.append(produto)

    return products


def generate_mini_codigo(linha):
    """Gera Mini Código tolerante a dados parciais (usa densidade se existir)."""
    dims = linha.get("dimensoes", {})
    codigo = linha.get("codigo_fornecedor", "")

    comp = dims.get("comprimento", 0)
    larg = dims.get("largura", 0)
    esp = dims.get("espessura", 0)

    dens_m = re.search(r"(D\d{2})", codigo, flags=re.IGNORECASE)
    densidade = (dens_m.group(1).upper() if dens_m else "")

    if larg and comp and esp:
        core = f"{larg}x{comp}x{esp}"
    elif larg and comp:
        core = f"{larg}x{comp}"
    else:
        core = ""

    if densidade and core:
        return f"{densidade}-{core}"
    return core or codigo


def get_realistic_fallback():
    """Fallback realista (não usado se OCR funcionar)."""
    return {
        "numero_requisicao":
        "REQ-2025-0045",
        "document_number":
        "GR-2025-0234",
        "po_number":
        "GR-2025-0234",
        "supplier_name":
        "Blocos Portugal SA",
        "delivery_date":
        "25/09/2025",
        "lines": [
            {
                "supplier_code": "BLC-D25-200x300x150",
                "description": "Bloco betão celular D25 200x300x150",
                "unit": "UNI",
                "qty": 48,
                "mini_codigo": "D25-200x300x150",
                "dimensoes": {
                    "comprimento": 300,
                    "largura": 200,
                    "espessura": 150
                },
            },
            {
                "supplier_code": "BLC-D30-200x600x200",
                "description": "Bloco betão celular D30 200x600x200",
                "unit": "UNI",
                "qty": 24,
                "mini_codigo": "D30-200x600x200",
                "dimensoes": {
                    "comprimento": 600,
                    "largura": 200,
                    "espessura": 200
                },
            },
        ],
        "totals": {
            "total_lines": 2,
            "total_quantity": 72
        },
    }


# ----------------- Mapeamento + Matching + Export -----------------


def map_supplier_codes(supplier, payload):
    mapped = []
    for l in payload.get("lines", []):
        supplier_code = l.get("supplier_code")
        mapping = CodeMapping.objects.filter(
            supplier=supplier, supplier_code=supplier_code).first()
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
            inbound=inbound,
            line_ref="OCR",
            issue=f"OCR extraction failed: {payload['error']}")

    inbound.parsed_payload = payload
    inbound.save()

    # criar linhas de receção
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

    # ligar à PO (se existir)
    po = PurchaseOrder.objects.filter(number=payload.get("po_number")).first()
    if po:
        inbound.po = po
        inbound.save()

    # Matching
    ok = 0
    issues = 0
    exceptions = []
    if inbound.po:
        for r in inbound.lines.all():
            pol = None
            if r.maybe_internal_sku:
                pol = POLine.objects.filter(
                    po=inbound.po, internal_sku=r.maybe_internal_sku).first()
            if not pol:
                issues += 1
                exceptions.append({
                    "line": r.supplier_code,
                    "issue": "Código não mapeado para SKU interno",
                    "suggested": "",
                })
                continue
            diff = float(r.qty_received) - float(pol.qty_ordered)
            if abs(diff) > float(pol.tolerance):
                issues += 1
                exceptions.append({
                    "line":
                    r.maybe_internal_sku,
                    "issue":
                    f"Quantidade divergente (recebida {r.qty_received} vs pedida {pol.qty_ordered} ± tol {pol.tolerance})",
                })
            else:
                ok += 1
    else:
        for r in inbound.lines.all():
            issues += 1
            exceptions.append({
                "line": r.supplier_code,
                "issue": "PO não identificada"
            })

    res, _ = MatchResult.objects.get_or_create(inbound=inbound)

    total_lines_in_doc = len(payload.get("lines", []))
    lines_read_successfully = ok
    first_error_line = None
    if exceptions:
        for idx, line in enumerate(payload.get("lines", []), 1):
            line_code = line.get("supplier_code", "")
            if any(line_code in ex.get("line", "") for ex in exceptions):
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
    res.certified_id = hashlib.sha256(
        (str(inbound.id) + str(payload)).encode()).hexdigest()[:16]
    res.save()

    inbound.exceptions.all().delete()
    for ex in exceptions:
        ExceptionTask.objects.create(inbound=inbound,
                                     line_ref=ex["line"],
                                     issue=ex["issue"])

    return res


def export_document_to_excel(inbound_id: int) -> HttpResponse:
    """Exporta para Excel no formato pedido (Req, Mini Código, Dimensões, Quantidade…)."""
    inbound = InboundDocument.objects.get(id=inbound_id)

    wb = Workbook()
    ws = wb.active
    ws.title = "Requisição Processada"

    headers = [
        "Nº Requisição", "Mini Código", "Dimensões (LxCxE)", "Quantidade",
        "Código Fornecedor", "Descrição"
    ]
    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="FF6B35",
                              end_color="FF6B35",
                              fill_type="solid")

    for col, h in enumerate(headers, 1):
        c = ws.cell(row=1, column=col, value=h)
        c.font = header_font
        c.fill = header_fill
        c.alignment = Alignment(horizontal="center")

    numero_req = inbound.parsed_payload.get("numero_requisicao",
                                            "") or f"REQ-{inbound.id}"

    for row, linha in enumerate(inbound.lines.all(), 2):
        dimensoes = ""
        mini_codigo = ""

        for payload_line in inbound.parsed_payload.get("lines", []):
            if payload_line.get("supplier_code") == linha.supplier_code:
                dims = payload_line.get("dimensoes", {})
                if dims and any(dims.values()):
                    larg = dims.get("largura", 0)
                    comp = dims.get("comprimento", 0)
                    esp = dims.get("espessura", 0)
                    if larg and comp and esp:
                        dimensoes = f"{larg}x{comp}x{esp}"
                    elif larg and comp:
                        dimensoes = f"{larg}x{comp}"
                mini_codigo = payload_line.get("mini_codigo", "")
                break

        ws.cell(row=row, column=1, value=numero_req)
        ws.cell(row=row,
                column=2,
                value=mini_codigo or linha.maybe_internal_sku)
        ws.cell(row=row, column=3, value=dimensoes)
        ws.cell(row=row, column=4, value=float(linha.qty_received))
        ws.cell(row=row, column=5, value=linha.supplier_code)
        ws.cell(row=row, column=6, value=linha.description)

    # auto width
    for column in ws.columns:
        max_len = 0
        letter = column[0].column_letter
        for cell in column:
            try:
                max_len = max(max_len, len(str(cell.value)))
            except Exception:
                pass
        ws.column_dimensions[letter].width = min(max_len + 2, 50)

    response = HttpResponse(
        content_type=
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    response[
        "Content-Disposition"] = f'attachment; filename="requisicao_{numero_req}_{inbound.id}.xlsx"'
    wb.save(response)
    return response
