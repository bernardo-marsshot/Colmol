
# -*- coding: utf-8 -*-
"""
services.py — robust invoice & delivery-note reader (open-source only)
- Prefers PDF native text (pdfplumber) and tables when available
- Falls back to ASCII/monospace parsing (regex)
- Final fallback to OCR (PaddleOCR) page-by-page for scans
- Returns a uniform dict structure usable by existing code
Compatibility helpers:
- parse_document(file_path): main entrypoint
- extract_invoice_data(file_path): wrapper to keep older calls working
- parse_pdf(file_path): wrapper to keep older calls working
Dependencies (install as needed):
  pip install pdfplumber pdf2image paddleocr opencv-python python-dateutil
System:
  apt-get install -y poppler-utils   # for pdf2image (pdftoppm)
"""
from __future__ import annotations
import re
import os
import tempfile
from typing import List, Optional, Dict, Any

# soft imports (module still loads if missing; features guarded)
try:
    import pdfplumber
except Exception:
    pdfplumber = None

try:
    from pdf2image import convert_from_path
except Exception:
    convert_from_path = None

# OCR soft dependency
_OCR = None
def _get_ocr():
    global _OCR
    if _OCR is not None:
        return _OCR
    try:
        from paddleocr import PaddleOCR
        _OCR = PaddleOCR(lang='en', use_angle_cls=True, show_log=False)
    except Exception:
        _OCR = None
    return _OCR

# ---------------------------
# Utilities
# ---------------------------
NUM_PT = re.compile(r'(?<!\\w)(?:\\d{1,3}(?:\\.\\d{3})*|\\d+)(?:,\\d+)?(?!\\w)')
DATE_GENERIC = re.compile(r'\\b(\\d{2})[\\/\\-](\\d{2})[\\/\\-](\\d{4})\\b')
DOCNO_RE = re.compile(r'\\b(?:GR|N|FT|FAT|FA|IN|INV|DN)\\s*[\\- ]?\\d{1,4}\\/\\d{4,7}|\\b[A-Z]{1,4}\\d?\\/\\d{6,}|\\bN4\\/\\d{7}\\b', re.I)
NIF_RE = re.compile(r'\\b(?:PT\\s*)?(\\d{9})\\b', re.I)
CURRENCY_RE = re.compile(r'\\b(EUR|USD|GBP|€|£|\\$)\\b', re.I)

def _to_float_pt(s: str) -> Optional[float]:
    if not s: return None
    s = s.strip()
    s2 = s.replace('.', '').replace(',', '.')
    try:
        return float(s2)
    except Exception:
        return None

def _iso_date_from_text(text: str) -> Optional[str]:
    m = DATE_GENERIC.search(text)
    if not m: return None
    d, mth, y = m.groups()
    return f"{y}-{mth}-{d}"

def _clean_text(t: str) -> str:
    t = re.sub(r'[ \\t]+', ' ', t)
    t = re.sub(r'\\n{3,}', '\\n\\n', t)
    return t.strip()

def _currency_from_text(text: str) -> Optional[str]:
    m = CURRENCY_RE.search(text)
    if not m: return None
    x = m.group(1).upper()
    return {'€':'EUR','£':'GBP','$':'USD'}.get(x, x)

# ---------------------------
# PDF text and tables
# ---------------------------
def _pdf_all_text(path: str) -> str:
    if not pdfplumber:
        return ""
    out = []
    try:
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                t = page.extract_text() or ""
                out.append(t)
    except Exception:
        return ""
    return "\\n".join(out)

def _pdf_all_tables(path: str) -> List[List[List[str]]]:
    if not pdfplumber:
        return []
    tables = []
    try:
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                try:
                    tbls = page.extract_tables() or []
                    for t in tbls:
                        norm = [[(c or '').strip() for c in row] for row in t]
                        if len(norm) >= 2:
                            tables.append(norm)
                except Exception:
                    continue
    except Exception:
        return []
    return tables

# ---------------------------
# ASCII (monospace) table parser
# ---------------------------
def _parse_ascii_blocks(text: str) -> List[Dict[str, Any]]:
    lines = [ln.rstrip() for ln in text.splitlines()]
    items = []
    for ln in lines:
        m_qty = NUM_PT.search(ln)
        if not m_qty:
            continue
        candidates = list(NUM_PT.finditer(ln))
        if not candidates:
            continue
        qty_m = candidates[-1]
        qty_txt = qty_m.group(0)
        qty = _to_float_pt(qty_txt)
        unit = None
        trail = ln[qty_m.end():].strip()
        m_unit = re.match(r'([A-Za-z]{1,4})\\b', trail)
        if m_unit:
            unit = m_unit.group(1).upper()
        code = None
        m_code = re.match(r'\\s*([A-Z0-9][A-Z0-9\\-\\.\\/]{4,})', ln, re.I)
        if m_code:
            code = m_code.group(1).strip()
        start = m_code.end() if m_code else 0
        end = qty_m.start()
        desc = ln[start:end].strip(" -|\\t")
        if qty is not None and (code or desc):
            items.append({
                "code": code,
                "description": re.sub(r'\\s{2,}', ' ', desc),
                "qty": qty,
                "unit": unit or "UN"
            })
    uniq = []
    seen = set()
    for it in items:
        key = (it.get("code"), it.get("description"), it.get("qty"))
        if key in seen: 
            continue
        seen.add(key)
        uniq.append(it)
    return uniq

# ---------------------------
# OCR fallback
# ---------------------------
def _ocr_text_from_pdf(path: str, max_pages: int = 10) -> str:
    if not convert_from_path:
        return ""
    ocr = _get_ocr()
    if not ocr:
        return ""
    try:
        pages = convert_from_path(path, dpi=200)  # get all pages, we'll slice below
    except Exception:
        return ""
    text_parts = []
    for i, img in enumerate(pages[:max_pages]):
        try:
            with tempfile.NamedTemporaryFile(suffix='.png', delete=True) as tmp:
                img.save(tmp.name, 'PNG')
                result = ocr.ocr(tmp.name, cls=True)
                for page in result:
                    for line in page:
                        t = line[1][0]
                        text_parts.append(t)
        except Exception:
            continue
    return "\\n".join(text_parts)

# ---------------------------
# Field extraction (generic)
# ---------------------------
def _extract_fields(text: str) -> Dict[str, Any]:
    fields = {}
    mdoc = DOCNO_RE.search(text)
    if mdoc:
        fields["doc_number"] = mdoc.group(0)
    d = _iso_date_from_text(text)
    if d:
        fields["doc_date"] = d
    nifs = [m.group(1) for m in NIF_RE.finditer(text)]
    if nifs:
        fields["supplier_tax_id"] = nifs[0]
        if len(nifs) > 1:
            fields["customer_tax_id"] = nifs[1]
    c = _currency_from_text(text)
    if c:
        fields["currency"] = c
    low = text.lower()
    if "guia de remessa" in low or "delivery note" in low:
        fields["doc_type"] = "delivery_note"
    elif "fatura" in low or "factura" in low or "invoice" in low:
        fields["doc_type"] = "invoice"
    elif "comunicação de saída" in low:
        fields["doc_type"] = "dispatch_note"
    else:
        fields["doc_type"] = "unknown"
    return fields

# ---------------------------
# Table to items heuristic
# ---------------------------
def _items_from_tables(tables: List[List[List[str]]]) -> List[Dict[str, Any]]:
    items = []
    for t in tables:
        if len(t) < 2: 
            continue
        header = t[0]
        body = t[1:]
        for row in body:
            if not row: 
                continue
            qty = None
            unit = None
            code = None
            desc = max(row, key=lambda x: len(x or "")) if row else ""
            for cell in row[::-1]:
                if NUM_PT.search(cell or ""):
                    m = list(NUM_PT.finditer(cell))[-1]
                    qty = _to_float_pt(m.group(0))
                    break
            for cell in row[-3:]:
                if cell and re.fullmatch(r'[A-Za-z]{1,4}', cell.strip()):
                    unit = cell.strip().upper()
                    break
            for cell in row[:3]:
                if cell and re.fullmatch(r'[A-Z0-9][A-Z0-9\\-/\\.]{5,}', cell.replace(' ', '')):
                    code = cell.strip()
                    break
            if qty is not None and (desc or code):
                items.append({
                    "code": code,
                    "description": re.sub(r'\\s{2,}', ' ', desc or ''),
                    "qty": qty,
                    "unit": unit or "UN"
                })
    uniq = []
    seen = set()
    for it in items:
        key = (it.get('code'), it.get('description'), it.get('qty'))
        if key in seen: 
            continue
        seen.add(key)
        uniq.append(it)
    return uniq

# ---------------------------
# Public API
# ---------------------------
def parse_document(file_path: str) -> Dict[str, Any]:
    """
    Main entrypoint: returns a normalized dict:
    {
      "doc_type": "...",
      "doc_number": "...",
      "doc_date": "YYYY-MM-DD",
      "supplier_tax_id": "...",
      "customer_tax_id": "...",
      "currency": "EUR|USD|GBP",
      "lines": [ {code, description, qty, unit}, ... ],
      "raw_text": "...",
      "confidence": 0.0..1.0
    }
    """
    text = ""
    is_pdf = str(file_path).lower().endswith(".pdf")
    tables = []
    if is_pdf and pdfplumber:
        text = _pdf_all_text(file_path)
        tables = _pdf_all_tables(file_path)
    if len((text or "").strip()) < 15 and is_pdf:
        ocr_text = _ocr_text_from_pdf(file_path, max_pages=12)
        if len(ocr_text) > len(text):
            text = ocr_text
    text = _clean_text(text or "")
    fields = _extract_fields(text)
    items = []
    if tables:
        items = _items_from_tables(tables)
    if not items:
        items = _parse_ascii_blocks(text)
    confidence = 0.35
    if fields.get("doc_type") != "unknown":
        confidence += 0.15
    if fields.get("doc_date"):
        confidence += 0.15
    if items:
        confidence += 0.25
    confidence = max(0.0, min(confidence, 1.0))
    result = {
        "doc_type": fields.get("doc_type", "unknown"),
        "doc_number": fields.get("doc_number"),
        "doc_date": fields.get("doc_date"),
        "supplier_tax_id": fields.get("supplier_tax_id"),
        "customer_tax_id": fields.get("customer_tax_id"),
        "currency": fields.get("currency") or "EUR",
        "lines": items,
        "raw_text": text,
        "confidence": confidence,
    }
    # Legacy compatibility: many UIs expect these keys
    legacy = {
        "produtos": items,            # old key for line items
        "texto_completo": text,       # old key for raw text
        "qr_codes": [],               # keep available even if empty
    }
    result.update(legacy)
    return result

def extract_invoice_data(file_path: str) -> Dict[str, Any]:
    return parse_document(file_path)

def parse_pdf(file_path: str) -> Dict[str, Any]:
    return parse_document(file_path)
