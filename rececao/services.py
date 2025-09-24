
import hashlib
from .models import InboundDocument, ReceiptLine, CodeMapping, MatchResult, ExceptionTask, POLine
from django.db import transaction

def fake_ocr_extract(file_path:str):
    """Stub OCR: returns a deterministic toy payload.
    In real use, plug AWS Textract / Google Document AI / Azure Form Recognizer.
    """
    # Demo payload with two lines
    payload = {
        "po_number": "PO-2025-0001",
        "lines": [
            {"supplier_code":"Bl D23 E150", "description":"Bloco D23 150", "unit":"UN", "qty": 20},
            {"supplier_code":"Bl D23 E100", "description":"Bloco D23 100", "unit":"UN", "qty": 10},
        ]
    }
    return payload

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
    # Extract
    payload = fake_ocr_extract(inbound.file.path)
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
    res.status = 'matched' if issues == 0 else 'exceptions'
    res.summary = {"lines_ok": ok, "lines_issues": issues}
    res.certified_id = hashlib.sha256((str(inbound.id)+str(payload)).encode()).hexdigest()[:16]
    res.save()

    # Store exception tasks
    inbound.exceptions.all().delete()
    for ex in exceptions:
        ExceptionTask.objects.create(inbound=inbound, line_ref=ex["line"], issue=ex["issue"])
    return res
