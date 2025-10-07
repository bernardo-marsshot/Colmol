# llm_extraction/gemini_persist.py
from dataclasses import dataclass
from typing import List, Optional, Dict, Any
from decimal import Decimal, InvalidOperation
import re
from django.db import transaction
from django.utils.text import slugify

from rececao.models import (
    Supplier, PurchaseOrder, InboundDocument, ReceiptLine, 
    CodeMapping, MatchResult, ExceptionTask
)

@dataclass
class LineDTO:
    supplier_code: str
    description: str
    unit: str
    qty_received: str
    meta: Dict[str, Any]

@dataclass
class DocumentDTO:
    doc_type: str
    number: str
    date: Optional[str]
    supplier_name: Optional[str]
    supplier_code: Optional[str]
    supplier_vat: Optional[str]
    po_number: Optional[str]
    file_path: str
    lines: List[LineDTO]
    extra: Dict[str, Any]

def _norm_qty(s: str) -> Decimal:
    """Normaliza quantidade: remove espaços, vírgulas→ponto, retorna Decimal."""
    if not s:
        return Decimal("0.000")
    s = str(s).strip().replace(" ", "")
    # PT format: 1.711,220 → 1711.220
    # EN format: 1,711.220 → 1711.220
    # Detectar formato PT (vírgula é decimal)
    if "," in s and "." in s:
        # Ambos presentes: assumir . = milhares, , = decimal
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        # Só vírgula: assumir decimal PT
        s = s.replace(",", ".")
    elif "." in s:
        # Só ponto: pode ser EN decimal ou PT milhares
        # Se há múltiplos pontos, são milhares
        if s.count(".") > 1:
            s = s.replace(".", "")
        # Senão, assumir decimal EN (manter)
    
    try:
        return Decimal(s).quantize(Decimal("0.001"))
    except InvalidOperation:
        return Decimal("0.000")

def _short_code_from_name(name: str) -> str:
    """Gera código curto a partir do nome (max 16 chars)."""
    base = slugify(name or "Fornecedor").upper().replace("-", "_")
    return re.sub(r"[^A-Z0-9_]", "", base)[:16] or "SUPPLIER"

def _suggest_internal_sku(supplier: Supplier, supplier_code: str) -> Optional[str]:
    """Procura SKU interno no CodeMapping."""
    try:
        m = CodeMapping.objects.get(supplier=supplier, supplier_code=supplier_code)
        return m.internal_sku
    except CodeMapping.DoesNotExist:
        return None

@transaction.atomic
def persist_document(obj: Dict[str, Any]) -> InboundDocument:
    """
    Persiste documento extraído pelo Gemini no Django.
    Compatível com estrutura existente do app rececao.
    """
    # Validação e mapping para DTO
    lines = [LineDTO(**ln) for ln in obj.get("lines", [])]
    dto = DocumentDTO(
        doc_type=(obj.get("doc_type") or "").strip(),
        number=(obj.get("number") or "").strip(),
        date=obj.get("date"),
        supplier_name=obj.get("supplier_name"),
        supplier_code=obj.get("supplier_code"),
        supplier_vat=obj.get("supplier_vat"),
        po_number=obj.get("po_number"),
        file_path=obj.get("file_path") or "",
        lines=lines,
        extra=obj.get("extra") or {},
    )

    # 1. SUPPLIER
    supplier = None
    if dto.supplier_code:
        supplier = Supplier.objects.filter(code=dto.supplier_code).first()
    if not supplier and dto.supplier_name:
        supplier = Supplier.objects.filter(name__iexact=dto.supplier_name).first()
    if not supplier:
        code = dto.supplier_code or _short_code_from_name(dto.supplier_name)
        supplier, _ = Supplier.objects.get_or_create(
            code=code, 
            defaults={"name": dto.supplier_name or code}
        )

    # 2. PURCHASE ORDER (opcional)
    po = None
    if dto.po_number:
        po, _ = PurchaseOrder.objects.get_or_create(
            number=dto.po_number, 
            defaults={"supplier": supplier}
        )
        if po.supplier_id != supplier.id:
            po = None  # Não forçar se pertencer a outro supplier

    # 3. INBOUND DOCUMENT (idempotente)
    inbound, created = InboundDocument.objects.get_or_create(
        supplier=supplier, 
        doc_type=dto.doc_type, 
        number=dto.number,
        defaults={
            "file": dto.file_path, 
            "po": po, 
            "parsed_payload": {
                **dto.extra,
                "extraction_method": "gemini",
                "lines_extracted": len(dto.lines)
            }
        }
    )
    
    if not created:
        # Merge payload
        merged = {**(inbound.parsed_payload or {}), **dto.extra}
        merged["extraction_method"] = "gemini"
        merged["lines_extracted"] = len(dto.lines)
        inbound.parsed_payload = merged
        if po and inbound.po_id is None:
            inbound.po = po
        if dto.file_path and not inbound.file:
            inbound.file = dto.file_path
        inbound.save()

    # 4. RECEIPT LINES (evitar duplicados)
    seen = set()
    for idx, ln in enumerate(dto.lines):
        key = (
            ln.supplier_code.strip(), 
            (ln.description or "").strip(), 
            (ln.unit or "UN").strip(), 
            _norm_qty(ln.qty_received), 
            idx
        )
        if key in seen:
            continue
        seen.add(key)
        
        maybe_internal = _suggest_internal_sku(supplier, ln.supplier_code.strip()) or ""
        
        ReceiptLine.objects.get_or_create(
            inbound=inbound,
            supplier_code=ln.supplier_code.strip(),
            description=(ln.description or "").strip(),
            unit=(ln.unit or "UN").strip(),
            qty_received=_norm_qty(ln.qty_received),
            defaults={
                "article_code": ln.supplier_code.strip(),  # Usar supplier_code como article_code
                "maybe_internal_sku": maybe_internal
            },
        )

    # 5. MATCH RESULT
    total = inbound.lines.count()
    issues = inbound.lines.filter(maybe_internal_sku="").count()  # Linhas sem mapping
    
    if total == 0:
        status = "pending"
    elif issues == 0:
        status = "matched"
    else:
        status = "exceptions"
    
    MatchResult.objects.update_or_create(
        inbound=inbound,
        defaults={
            "status": status, 
            "summary": {
                "total_lines": total, 
                "lines_with_issues": issues,
                "extraction_method": "gemini"
            }
        }
    )
    
    return inbound
