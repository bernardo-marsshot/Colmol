# rececao/services.py
import hashlib
import json
import os
import re
import base64
import requests
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

# --- QR code detection (usando OpenCV) ---
try:
    import cv2
    import numpy as np
    QR_CODE_ENABLED = True
    print("✅ QR code detection disponível (OpenCV)")
except ImportError:
    QR_CODE_ENABLED = False
    print("⚠️ QR code não disponível (instale opencv-python para ativar)")

# Se precisares especificar o caminho do tesseract no Windows:
# pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

# --- Configuração Ollama ---
OLLAMA_API_URL = os.environ.get("OLLAMA_API_URL", "")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llava:latest")
OLLAMA_ENABLED = bool(OLLAMA_API_URL)

if OLLAMA_ENABLED:
    print(f"✅ Ollama Vision habilitado: {OLLAMA_API_URL} (modelo: {OLLAMA_MODEL})")
else:
    print("⚠️ Ollama Vision desabilitado (defina OLLAMA_API_URL para ativar)")

# ----------------- Ollama Vision -----------------

def extract_with_ollama_vision(file_path: str):
    """
    Extrai dados de documento usando Ollama Vision como fallback.
    Converte imagem/PDF em base64 e envia para modelo LLaVA.
    
    LIMITAÇÃO: PDFs multi-página - processa apenas a PRIMEIRA página.
    Se dados críticos estiverem em páginas subsequentes, o fallback pode não recuperá-los.
    """
    if not OLLAMA_ENABLED:
        print("⚠️ Ollama não disponível - fallback desabilitado")
        return None
    
    try:
        print("🤖 Tentando extração com Ollama Vision...")
        
        # Converter primeira página do PDF ou imagem para base64
        ext = os.path.splitext(file_path)[1].lower()
        if ext == '.pdf':
            # Converter primeira página do PDF para imagem
            pages = convert_from_path(file_path, dpi=150, first_page=1, last_page=1)
            if not pages:
                return None
            img = pages[0]
        else:
            img = Image.open(file_path)
        
        # Converter para base64
        buffered = BytesIO()
        img.save(buffered, format="JPEG")
        img_base64 = base64.b64encode(buffered.getvalue()).decode()
        
        # Prompt para extrair dados estruturados
        prompt = """Analisa esta Guia de Remessa portuguesa e extrai as seguintes informações em formato JSON:

{
  "numero_requisicao": "número da requisição ou documento",
  "document_number": "número do documento",
  "supplier_name": "nome do fornecedor",
  "delivery_date": "data de entrega (formato DD-MM-YYYY)",
  "produtos": [
    {
      "artigo": "código do artigo/produto",
      "descricao": "descrição do produto",
      "quantidade": número (SEM separadores de milhares - ex: 1234 não 1.234),
      "unidade": "unidade (ML, UN, etc)",
      "preco_unitario": número (decimal com ponto - ex: 12.50 não 12,50),
      "total": número (decimal com ponto - ex: 1234.56 não 1.234,56),
      "dimensoes": {
        "largura": número ou null,
        "comprimento": número ou null,
        "espessura": número ou null
      }
    }
  ]
}

IMPORTANTE:
- Números: use APENAS PONTO para decimais (12.50)
- NÃO use separadores de milhares (escreva 1234 não 1.234)
- NÃO use vírgulas em números (escreva 12.5 não 12,5)

Responde APENAS com o JSON, sem texto adicional."""

        # Chamar API do Ollama
        response = requests.post(
            f"{OLLAMA_API_URL}/generate",
            json={
                "model": OLLAMA_MODEL,
                "prompt": prompt,
                "images": [img_base64],
                "stream": False,
                "options": {
                    "num_predict": 2048
                }
            },
            timeout=300
        )
        
        if response.status_code != 200:
            print(f"❌ Ollama erro HTTP {response.status_code}")
            return None
        
        result = response.json()
        response_text = result.get("response", "")
        
        # Tentar extrair JSON da resposta
        try:
            # Procurar por JSON na resposta (pode ter texto antes/depois)
            json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
            if json_match:
                parsed_data = json.loads(json_match.group())
                print(f"✅ Ollama extraiu {len(parsed_data.get('produtos', []))} produtos")
                return parsed_data
            else:
                print("⚠️ Ollama não retornou JSON válido")
                return None
        except json.JSONDecodeError as e:
            print(f"❌ Erro ao parsear JSON do Ollama: {e}")
            print(f"Resposta: {response_text[:200]}")
            return None
            
    except Exception as e:
        print(f"❌ Erro no Ollama Vision: {e}")
        return None


def safe_numeric(value, default=0):
    """
    Converte valor para float/int de forma segura.
    
    DESIGN PRAGMÁTICO:
    - Normaliza apenas formatos CLARAMENTE identificáveis
    - Confia que Ollama Vision retorna valores já normalizados do documento
    - Evita sobre-engenharia em casos ambíguos
    
    Casos claros:
    - Ambos separadores: determina pela posição
    - Múltiplos separadores: milhares
    - Vírgula única: decimal europeu
    - Ponto único: mantém como está (pode ser decimal ou já convertido)
    """
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        try:
            # Limpar moedas e espaços
            cleaned = value.strip()
            cleaned = re.sub(r'[€$£¥R\s]', '', cleaned)
            
            if not cleaned:
                return default
            
            has_dot = '.' in cleaned
            has_comma = ',' in cleaned
            
            # Caso 1: Ambos separadores → formato claro
            if has_dot and has_comma:
                dot_pos = cleaned.rfind('.')
                comma_pos = cleaned.rfind(',')
                if dot_pos > comma_pos:
                    # Americano: 1,234.56
                    cleaned = cleaned.replace(',', '')
                else:
                    # Europeu: 1.234,56
                    cleaned = cleaned.replace('.', '').replace(',', '.')
            
            # Caso 2: Múltiplos separadores → milhares
            elif cleaned.count('.') > 1:
                cleaned = cleaned.replace('.', '')
            elif cleaned.count(',') > 1:
                cleaned = cleaned.replace(',', '')
            
            # Caso 3: Vírgula única → decimal europeu
            elif cleaned.count(',') == 1:
                cleaned = cleaned.replace(',', '.')
            
            # Caso 4: Ponto único → heurística balanceada
            # LIMITAÇÃO CONHECIDA: casos ambíguos não têm solução perfeita sem locale
            elif cleaned.count('.') == 1:
                parts = cleaned.split('.')
                before_str = parts[0].lstrip('-+')
                after_str = parts[1] if len(parts) > 1 else ""
                
                # Heurística: milhares PT se 3 dígitos após E valor antes 1-999
                # Cobre casos típicos: "1.234"→1234, "12.345"→12345
                # Exclui: "0.333"→0.333, "1000.123"→1000.123 (já muito grande)
                try:
                    before_val = int(before_str) if before_str.isdigit() else 0
                    if len(after_str) == 3 and 1 <= before_val <= 999:
                        # Provavelmente milhares PT
                        cleaned = cleaned.replace('.', '')
                except (ValueError, AttributeError):
                    pass  # Manter como está
            
            result = float(cleaned)
            return int(result) if result.is_integer() else result
            
        except (ValueError, AttributeError):
            return default
    return default


def normalize_ollama_payload(ollama_result: dict, tesseract_qr_codes: list) -> dict:
    """
    Normaliza completamente o payload retornado pelo Ollama Vision.
    Garante schema consistente e conversão segura de todos os campos.
    
    Retorna estrutura normalizada compatível com downstream consumers.
    """
    normalized = {}
    
    # 1. Metadados básicos (strings)
    normalized["numero_requisicao"] = ollama_result.get("numero_requisicao") or ""
    normalized["document_number"] = ollama_result.get("document_number") or ""
    normalized["po_number"] = ollama_result.get("po_number") or ""
    normalized["supplier_name"] = ollama_result.get("supplier_name") or ""
    normalized["delivery_date"] = ollama_result.get("delivery_date") or ""
    
    # 2. QR codes (sempre usar os detectados pelo Tesseract)
    normalized["qr_codes"] = tesseract_qr_codes if tesseract_qr_codes else []
    
    # 3. Normalizar produtos (novo formato)
    raw_produtos = ollama_result.get("produtos")
    if raw_produtos and isinstance(raw_produtos, list):
        normalized_produtos = []
        for item in raw_produtos:
            # Ignorar items que não são dicts
            if not isinstance(item, dict):
                continue
            
            # Normalizar campos do produto
            produto = {
                "artigo": item.get("artigo") or "",
                "descricao": item.get("descricao") or "",
                "quantidade": safe_numeric(item.get("quantidade"), 0),
                "unidade": item.get("unidade") or "",
                "preco_unitario": safe_numeric(item.get("preco_unitario"), 0),
                "total": safe_numeric(item.get("total"), 0),
            }
            
            # Dimensões (opcional)
            dim = item.get("dimensoes")
            if dim and isinstance(dim, dict):
                produto["dimensoes"] = {
                    "largura": safe_numeric(dim.get("largura")),
                    "comprimento": safe_numeric(dim.get("comprimento")),
                    "espessura": safe_numeric(dim.get("espessura")),
                }
            else:
                produto["dimensoes"] = None
            
            normalized_produtos.append(produto)
        
        normalized["produtos"] = normalized_produtos
    else:
        normalized["produtos"] = []
    
    # 4. Normalizar lines (formato legado)
    raw_lines = ollama_result.get("lines")
    if raw_lines and isinstance(raw_lines, list):
        normalized_lines = []
        for item in raw_lines:
            if not isinstance(item, dict):
                continue
            
            line = {
                "supplier_code": item.get("supplier_code") or "",
                "description": item.get("description") or "",
                "qty": safe_numeric(item.get("qty"), 0),
                "unit": item.get("unit") or "",
                "unit_price": safe_numeric(item.get("unit_price"), 0),
                "total": safe_numeric(item.get("total"), 0),
            }
            normalized_lines.append(line)
        
        normalized["lines"] = normalized_lines
    else:
        normalized["lines"] = []
    
    # 5. SEMPRE recalcular totals (nunca confiar no LLM)
    total_qty = 0
    for p in normalized["produtos"]:
        total_qty += p.get("quantidade", 0)
    for l in normalized["lines"]:
        total_qty += l.get("qty", 0)
    
    normalized["totals"] = {
        "total_lines": len(normalized["produtos"]) + len(normalized["lines"]),
        "total_quantity": total_qty
    }
    
    return normalized


def calculate_confidence_score(payload: dict) -> float:
    """
    Calcula score de confiança (0-100) dos dados extraídos.
    Score alto = dados completos e válidos.
    Score baixo = dados faltando ou suspeitos.
    """
    score = 0
    max_score = 100
    
    # Documento tem número? (+10)
    if payload.get("document_number") or payload.get("numero_requisicao"):
        score += 10
    
    # Tem fornecedor? (+10)
    if payload.get("supplier_name"):
        score += 10
    
    # Tem data? (+5)
    if payload.get("delivery_date"):
        score += 5
    
    # Tem produtos/linhas? (+20)
    produtos = payload.get("produtos", [])
    lines = payload.get("lines", [])
    if produtos or lines:
        score += 20
        
        # Verificar qualidade dos produtos
        items = produtos if produtos else lines
        if len(items) > 0:
            # Pelo menos 1 produto (+10)
            score += 10
            
            # Produtos têm informação completa? (+20)
            complete_items = 0
            for item in items:
                has_code = bool(item.get("artigo") or item.get("supplier_code"))
                has_qty = bool(item.get("quantidade") or item.get("qty"))
                has_desc = bool(item.get("descricao") or item.get("description"))
                
                if has_code and has_qty and has_desc:
                    complete_items += 1
            
            # Percentagem de produtos completos
            completeness = complete_items / len(items)
            score += int(20 * completeness)
            
            # Bonus: Produtos têm dimensões? (+10)
            has_dimensions = any(
                item.get("dimensoes") for item in items
            )
            if has_dimensions:
                score += 10
            
            # Bonus: Tem preços? (+5)
            has_prices = any(
                item.get("preco_unitario") or item.get("total") for item in items
            )
            if has_prices:
                score += 5
        else:
            # Tem campo mas vazio = suspeito
            score -= 10
    
    # Penalidade: Se não tem produtos/linhas é falha crítica
    if not produtos and not lines:
        score = min(score, 20)  # Cap no máximo 20%
    
    # Normalizar entre 0-100
    score = max(0, min(100, score))
    
    return score


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
    """
    Sistema de extração inteligente:
    - Se OLLAMA configurado: usa APENAS Ollama Vision (visão computacional direta)
    - Se não configurado: usa Tesseract OCR tradicional
    """
    ext = os.path.splitext(file_path)[1].lower()
    qr_codes = []
    
    # ========== OLLAMA VISION (MÉTODO PRIMÁRIO SE CONFIGURADO) ==========
    if OLLAMA_ENABLED:
        print("🤖 Usando Ollama Vision (método primário)...")
        
        # Detectar QR codes primeiro (Tesseract ainda é bom para isso)
        if QR_CODE_ENABLED:
            try:
                if ext == ".pdf":
                    pages = convert_from_path(file_path, dpi=300, first_page=1, last_page=1)
                    if pages:
                        qr_codes = detect_and_read_qrcodes(pages[0], page_number=1)
                elif ext in [".jpg", ".jpeg", ".png", ".tiff", ".bmp"]:
                    img = Image.open(file_path)
                    qr_codes = detect_and_read_qrcodes(img, page_number=1)
                
                if qr_codes:
                    print(f"✅ {len(qr_codes)} QR code(s) detectado(s)")
            except Exception as e:
                print(f"⚠️ Erro ao detectar QR codes: {e}")
        
        # Extrair dados com Ollama Vision
        ollama_result = extract_with_ollama_vision(file_path)
        
        if ollama_result:
            # Normalizar payload
            result = normalize_ollama_payload(ollama_result, qr_codes)
            confidence_score = calculate_confidence_score(result)
            
            result["_extraction_method"] = "ollama_vision"
            result["_confidence_score"] = confidence_score
            
            print(f"✅ Extração via OLLAMA VISION (confiança: {confidence_score:.1f}%)")
            save_extraction_to_json(result)
            return result
        else:
            print("❌ Ollama Vision falhou")
            error_result = {
                "error": "Ollama Vision extraction failed",
                "numero_requisicao": f"ERROR-{os.path.basename(file_path)}",
                "document_number": "",
                "po_number": "",
                "supplier_name": "",
                "delivery_date": "",
                "qr_codes": qr_codes,
                "produtos": [],
                "lines": [],
                "totals": {
                    "total_lines": 0,
                    "total_quantity": 0
                },
                "_extraction_method": "ollama_vision",
                "_confidence_score": 0,
            }
            save_extraction_to_json(error_result)
            return error_result
    
    # ========== TESSERACT OCR (FALLBACK SE OLLAMA NÃO CONFIGURADO) ==========
    print("📄 Usando Tesseract OCR (Ollama não configurado)...")
    
    text_content = ""
    if ext == ".pdf":
        text_content, qr_codes = extract_text_from_pdf(file_path)
    elif ext in [".jpg", ".jpeg", ".png", ".tiff", ".bmp"]:
        text_content, qr_codes = extract_text_from_image(file_path)

    # Pré-visualização
    if text_content:
        preview = "\n".join(text_content.splitlines()[:60])
        print("---- OCR PREVIEW (primeiras linhas) ----")
        print(preview)
        print("----------------------------------------")

    if qr_codes:
        print(f"✅ {len(qr_codes)} QR code(s) detectado(s)")

    if not text_content.strip():
        print("❌ Tesseract OCR vazio")
        error_result = {
            "error": "OCR failed - no text extracted",
            "numero_requisicao": f"ERROR-{os.path.basename(file_path)}",
            "document_number": "",
            "po_number": "",
            "supplier_name": "",
            "delivery_date": "",
            "qr_codes": qr_codes,
            "produtos": [],
            "lines": [],
            "totals": {
                "total_lines": 0,
                "total_quantity": 0
            },
            "_extraction_method": "tesseract",
            "_confidence_score": 0,
        }
        save_extraction_to_json(error_result)
        return error_result

    result = parse_portuguese_document(text_content, qr_codes)
    confidence_score = calculate_confidence_score(result)
    
    result["_extraction_method"] = "tesseract"
    result["_confidence_score"] = confidence_score
    
    print(f"✅ Extração via TESSERACT (confiança: {confidence_score:.1f}%)")
    save_extraction_to_json(result)
    return result


def extract_text_from_pdf(file_path: str):
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
            # Mesmo com texto embutido, tenta detectar QR codes
            qr_codes = []
            if QR_CODE_ENABLED:
                try:
                    print("🔍 Procurando QR codes no PDF...")
                    pages = convert_from_path(file_path, dpi=300)
                    for page_num, page_img in enumerate(pages, start=1):
                        page_qr = detect_and_read_qrcodes(page_img,
                                                          page_number=page_num)
                        qr_codes.extend(page_qr)
                except Exception as e:
                    print(f"⚠️ Erro ao buscar QR codes: {e}")
            return text.strip(), qr_codes

        print("📄 PDF sem texto embutido—usar OCR…")
        return extract_text_from_pdf_with_ocr(file_path)

    except Exception as e:
        print(f"❌ Erro no extract_text_from_pdf: {e}")
        return extract_text_from_pdf_with_ocr(file_path)


def parse_qrcode_fiscal_pt(qr_data: str):
    """Parse de QR code fiscal português (formato A:valor*B:valor*...) com nomes descritivos."""

    # Mapeamento dos códigos para nomes descritivos (Especificações Técnicas AT)
    FIELD_NAMES = {
        "A": "nif_emitente",
        "B": "nif_adquirente",
        "C": "pais_adquirente",
        "D": "tipo_documento",
        "E": "estado_documento",
        "F": "data_documento",
        "G": "identificacao_documento",
        "H": "atcud",
        "I1": "espaco_fiscal",
        "I2": "base_tributavel_isenta_iva",
        "I3": "base_tributavel_taxa_reduzida",
        "I4": "total_iva_taxa_reduzida",
        "I5": "base_tributavel_taxa_intermedia",
        "I6": "total_iva_taxa_intermedia",
        "I7": "base_tributavel_taxa_normal",
        "I8": "total_iva_taxa_normal",
        "J1": "espaco_fiscal_2",
        "J2": "base_tributavel_isenta_iva_2",
        "J3": "base_tributavel_taxa_reduzida_2",
        "J4": "total_iva_taxa_reduzida_2",
        "J5": "base_tributavel_taxa_intermedia_2",
        "J6": "total_iva_taxa_intermedia_2",
        "J7": "base_tributavel_taxa_normal_2",
        "J8": "total_iva_taxa_normal_2",
        "K1": "espaco_fiscal_3",
        "K2": "base_tributavel_isenta_iva_3",
        "K3": "base_tributavel_taxa_reduzida_3",
        "K4": "total_iva_taxa_reduzida_3",
        "K5": "base_tributavel_taxa_intermedia_3",
        "K6": "total_iva_taxa_intermedia_3",
        "K7": "base_tributavel_taxa_normal_3",
        "K8": "total_iva_taxa_normal_3",
        "L": "nao_sujeito_iva",
        "M": "imposto_selo",
        "N": "total_impostos",
        "O": "total_documento",
        "P": "retencao_na_fonte",
        "Q": "hash",
        "R": "certificado",
        "S": "outras_infos"
    }

    try:
        if not qr_data or "*" not in qr_data:
            return None

        parsed_raw = {}
        fields = qr_data.split("*")

        for field in fields:
            if ":" in field:
                key, value = field.split(":", 1)
                parsed_raw[key] = value

        # Valida se é realmente um QR fiscal português
        # QR fiscal deve ter pelo menos o campo A (NIF emitente)
        if not parsed_raw or "A" not in parsed_raw:
            return None

        # Converte para nomes descritivos
        parsed = {}
        for code, value in parsed_raw.items():
            field_name = FIELD_NAMES.get(code, code)
            parsed[field_name] = value

        return parsed if parsed else None
    except Exception as e:
        print(f"⚠️ Erro ao parsear QR fiscal: {e}")
        return None


def detect_and_read_qrcodes(image, page_number=None):
    """Lê QR codes usando OpenCV e retorna lista estruturada."""
    if not QR_CODE_ENABLED:
        return []

    try:
        arr = np.array(image)
        if len(arr.shape) == 3 and arr.shape[2] == 3:
            arr = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
        elif len(arr.shape) == 3 and arr.shape[2] == 4:
            arr = cv2.cvtColor(arr, cv2.COLOR_RGBA2BGR)

        # Usa o detector de QR code do OpenCV
        detector = cv2.QRCodeDetector()
        data, vertices_array, _ = detector.detectAndDecode(arr)

        result = []
        if vertices_array is not None and data:
            print(f"✅ QR: {data[:80]}…")

            # Tenta parsear QR code fiscal português
            parsed = parse_qrcode_fiscal_pt(data)
            if parsed:
                # Se parseou com sucesso, coloca os dados estruturados no campo "data"
                qr_info = {"data": parsed, "raw_data": data}
            else:
                # Se não conseguiu parsear, mantém como string
                qr_info = {"data": data}

            if page_number is not None:
                qr_info["page"] = page_number

            result.append(qr_info)

        # Tenta detectar múltiplos QR codes (OpenCV 4.5.4+)
        try:
            multi_data = detector.detectAndDecodeMulti(arr)
            if multi_data[0]:  # Se detectou algum
                for i, qr_data in enumerate(multi_data[1]):
                    # Verifica se já não foi adicionado
                    already_added = False
                    for existing in result:
                        if existing.get("raw_data") == qr_data or existing.get(
                                "data") == qr_data:
                            already_added = True
                            break

                    if qr_data and not already_added:
                        print(f"✅ QR: {qr_data[:80]}…")

                        # Tenta parsear QR code fiscal português
                        parsed = parse_qrcode_fiscal_pt(qr_data)
                        if parsed:
                            qr_info = {"data": parsed, "raw_data": qr_data}
                        else:
                            qr_info = {"data": qr_data}

                        if page_number is not None:
                            qr_info["page"] = page_number

                        result.append(qr_info)
        except:
            pass  # Versão do OpenCV pode não suportar detectAndDecodeMulti

        return result
    except Exception as e:
        print(f"⚠️ QR erro: {e}")
        return []


def extract_text_from_pdf_with_ocr(file_path: str):
    """Converte todas as páginas para imagem e aplica Tesseract."""
    try:
        print("📄 Converter PDF → imagens (OCR)…")
        pages = convert_from_path(file_path, dpi=300)
        all_text = ""
        all_qr_codes = []
        for i, page in enumerate(pages, 1):
            print(f"🔍 Página {i}/{len(pages)}")
            qr_codes = detect_and_read_qrcodes(page, page_number=i)
            all_qr_codes.extend(qr_codes)
            page_text = pytesseract.image_to_string(
                page, config="--psm 6 --oem 3 -l por", lang="por")
            if page_text.strip():
                all_text += f"\n--- Página {i} ---\n{page_text}\n"
        print(f"✅ OCR completo: {len(pages)} páginas")
        return all_text.strip(), all_qr_codes
    except Exception as e:
        print(f"❌ OCR PDF erro: {e}")
        return "", []


def extract_text_from_image(file_path: str):
    """OCR para imagem ( + leitura de QR)."""
    try:
        img = Image.open(file_path)
        qr_codes = detect_and_read_qrcodes(img)
        ocr_text = pytesseract.image_to_string(img,
                                               config="--psm 6 --oem 3 -l por",
                                               lang="por")
        return ocr_text.strip(), qr_codes
    except Exception as e:
        print(f"❌ OCR imagem erro: {e}")
        return "", []


# ----------------- PARSE: heurísticas PT -----------------


def extract_guia_remessa_products(text: str):
    """
    Extrai produtos da tabela de Guia de Remessa com parser flexível.
    Campos: Artigo, Descrição, Lote Produção, Quant., Un., Vol., Preço Un., Desconto, Iva, Total
    """
    products = []
    lines = text.split("\n")

    current_ref = ""

    # Regex para detectar referências de ordem (mais flexível)
    ref_pattern = re.compile(
        r"^\s*(\d[A-Z]{2,6}\s+N[oº°]\s*\d+[/\-]\d+[A-Z]{0,4}\s+de\s+\d{2}-\d{2}-\d{4})",
        re.IGNORECASE)

    # Regex mais flexível para linha de produto
    # Formato: E0748001901  131,59 1  34,00 3,00 ML 3,99 23,00 5159-250602064 BALTIC fb, TOFFEE
    # Artigo: letras + números (mais flexível)
    # Volume: pode ser decimal
    # Lote: pode estar vazio ou ter vários formatos
    # Unidade: pode ter 2-10 caracteres
    product_pattern = re.compile(
        r"^([A-Z]+\d+[A-Z0-9]*)\s+"  # Artigo (flexível: E0748001901, ABC123, etc.)
        r"([\d,\.]+)\s+"  # Total
        r"([\d,\.]+)\s+"  # Volume (aceita decimais)
        r"([\d,\.]+)\s+"  # Quantidade
        r"([\d,\.]+)\s+"  # Desconto
        r"([A-Z]{2,10})\s+"  # Unidade (mais flexível)
        r"([\d,\.]+)\s+"  # Preço Unitário
        r"([\d,\.]+)\s+"  # IVA
        r"([\w\-#]*)\s*"  # Lote (opcional, pode estar vazio)
        r"(.+?)\s*$",  # Descrição (resto da linha)
        re.IGNORECASE)

    for line in lines:
        stripped = line.strip()

        # Verifica se é uma referência de ordem
        ref_match = ref_pattern.match(stripped)
        if ref_match:
            current_ref = ref_match.group(1).strip()
            continue

        # Verifica se é uma linha de produto
        prod_match = product_pattern.match(stripped)
        if prod_match:
            try:
                # Função auxiliar para normalizar números PT/EN
                def normalize_number(value: str) -> float:
                    """
                    Converte número para float, suportando formatos PT e EN.
                    PT: 1.234,56 (ponto=milhares, vírgula=decimal)
                    EN: 1,234.56 ou 1234.56 (ponto=decimal)
                    """
                    value = value.strip()

                    # Se tem vírgula, assume formato PT (vírgula é decimal)
                    if "," in value:
                        # Remove pontos (separadores de milhares)
                        value = value.replace(".", "")
                        # Substitui vírgula por ponto
                        value = value.replace(",", ".")
                    # Se tem ponto mas não tem vírgula, assume formato EN (ponto é decimal)
                    # Remove apenas vírgulas que seriam separadores de milhares
                    else:
                        value = value.replace(",", "")

                    return float(value)

                artigo = prod_match.group(1).strip()
                total = normalize_number(prod_match.group(2))
                volume = normalize_number(prod_match.group(3))
                quantidade = normalize_number(prod_match.group(4))
                desconto = normalize_number(prod_match.group(5))
                unidade = prod_match.group(6).strip()
                preco_un = normalize_number(prod_match.group(7))
                iva = normalize_number(prod_match.group(8))
                lote = prod_match.group(9).strip() if prod_match.group(
                    9) else ""
                descricao = prod_match.group(10).strip()

                # Validações básicas
                if not artigo or not descricao:
                    continue

                product = {
                    "referencia_ordem": current_ref if current_ref else None,
                    "artigo": artigo,
                    "descricao": descricao,
                    "lote_producao": lote if lote else None,
                    "quantidade": quantidade,
                    "unidade": unidade,
                    "volume": volume,
                    "preco_unitario": preco_un,
                    "desconto": desconto,
                    "iva": iva,
                    "total": total
                }

                products.append(product)
            except (ValueError, IndexError) as e:
                print(
                    f"⚠️ Erro ao parsear linha de produto '{stripped[:50]}...': {e}"
                )
                continue

    if products:
        print(f"✅ Extraídos {len(products)} produtos da Guia de Remessa")
    else:
        print("⚠️ Nenhum produto encontrado no formato Guia de Remessa")

    return products


def parse_portuguese_document(text: str, qr_codes=None):
    """Extrai cabeçalho (req/doc/fornecedor/data) e linhas de produto."""
    if qr_codes is None:
        qr_codes = []

    lines = text.split("\n")
    result = {
        "numero_requisicao": "",
        "document_number": "",
        "po_number": "",
        "supplier_name": "",
        "delivery_date": "",
        "qr_codes": qr_codes,
        "produtos": [],  # Nova estrutura para produtos da guia de remessa
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
                # Não copiar para po_number aqui - será extraído depois

        if not result["delivery_date"]:
            m = re.search(patterns["data"], ln)
            if m:
                result["delivery_date"] = m.group(1)

        if not result["supplier_name"]:
            m = re.search(patterns["fornecedor"], low)
            if m:
                result["supplier_name"] = m.group(1).title()

    # Extrai produtos da Guia de Remessa (novo formato)
    guia_products = extract_guia_remessa_products(text)
    if guia_products:
        result["produtos"] = guia_products
        result["totals"]["total_lines"] = len(guia_products)
        result["totals"]["total_quantity"] = sum(p["quantidade"]
                                                 for p in guia_products)
        
        # Tenta extrair po_number das referências de ordem (ex: "1ECWH Nº 10874/25EU")
        if not result["po_number"] and guia_products:
            # Procura padrão "CODIGO Nº" nas referências de ordem
            for produto in guia_products:
                ref = produto.get("referencia_ordem", "")
                # Match: qualquer código alfanumérico seguido de "Nº" ou "N."
                po_match = re.match(r'^([A-Z0-9]+)\s+[NnºN]', ref, re.IGNORECASE)
                if po_match:
                    result["po_number"] = po_match.group(1).upper()
                    break
    else:
        # Fallback: usa extração antiga se não encontrar produtos no novo formato
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

    # Fallback universal: se ainda não tem po_number, usa document_number
    if not result["po_number"] and result["document_number"]:
        result["po_number"] = result["document_number"]

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

    # Suporta novo formato com 'produtos' (Guia de Remessa extraída)
    if "produtos" in payload and payload["produtos"]:
        for produto in payload["produtos"]:
            # Extrair código do fornecedor da referência de ordem (ex: "1ECWH Nº 10874/25EU" -> "1ECWH")
            referencia = produto.get("referencia_ordem", "")
            supplier_code = referencia.split(" ")[0] if referencia else ""
            
            # Artigo/SKU do produto
            article_code = produto.get("artigo", "")
            
            # IMPORTANTE: Lookup usando article_code, não supplier_code!
            # supplier_code (ex:"1ECWH") é igual para todas as linhas deste fornecedor
            # article_code (ex:"E0748001901") é único por produto
            mapping = CodeMapping.objects.filter(
                supplier=supplier, supplier_code=article_code).first()
            mapped.append({
                "supplier_code": supplier_code,
                "article_code": article_code,
                "description": produto.get("descricao", ""),
                "unit": produto.get("unidade", "UN"),
                "qty": produto.get("quantidade", 0),
                "internal_sku": (mapping.internal_sku if mapping else None),
                "confidence": (mapping.confidence if mapping else 0.0),
            })
    # Formato antigo com 'lines' (no formato antigo, supplier_code era o SKU do produto)
    elif "lines" in payload:
        for l in payload.get("lines", []):
            supplier_code = l.get("supplier_code")
            mapping = CodeMapping.objects.filter(
                supplier=supplier, supplier_code=supplier_code).first()
            mapped.append({
                **l,
                "article_code": supplier_code,  # No formato antigo, supplier_code era o artigo/SKU
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
            article_code=ml.get("article_code", ""),
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
            # Verificar se código não está mapeado
            # IMPORTANTE: Lookup usando article_code (SKU do produto), não supplier_code (referência da ordem)
            mapping = CodeMapping.objects.filter(
                supplier=inbound.supplier,
                supplier_code=r.article_code
            ).first()
            
            if not mapping:
                issues += 1
                exceptions.append({
                    "line": r.article_code,
                    "issue": "Código não mapeado para SKU interno",
                    "suggested": "",
                })
                continue
            
            # Verificar se quantidade recebida EXCEDE a quantidade encomendada (do CodeMapping)
            qty_ordered = float(mapping.qty_ordered or 0)  # Proteção contra None
            if float(r.qty_received) > qty_ordered:
                issues += 1
                exceptions.append({
                    "line": r.article_code,
                    "issue": f"Quantidade excedida (recebida {r.qty_received} vs encomendada {qty_ordered})",
                })
                continue
            
            ok += 1
    else:
        for r in inbound.lines.all():
            issues += 1
            exceptions.append({
                "line": r.supplier_code,
                "issue": "PO não identificada"
            })

    res, _ = MatchResult.objects.get_or_create(inbound=inbound)

    # Suporta ambos os formatos (produtos ou lines)
    doc_items = payload.get("produtos", payload.get("lines", []))
    total_lines_in_doc = len(doc_items)
    lines_read_successfully = ok
    first_error_line = None
    if exceptions:
        for idx, item in enumerate(doc_items, 1):
            # Tenta ambos os campos (artigo para produtos, supplier_code para lines)
            item_code = item.get("artigo", item.get("supplier_code", ""))
            if any(item_code in ex.get("line", "") for ex in exceptions):
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

        # Formato Guia de Remessa (novo): procura em 'produtos' usando article_code
        if inbound.parsed_payload.get("produtos"):
            for produto in inbound.parsed_payload.get("produtos", []):
                # Match usando article_code (código do produto único)
                if produto.get("artigo") == linha.article_code:
                    dims = produto.get("dimensoes", {})
                    if dims and any(dims.values()):
                        larg = dims.get("largura", 0)
                        comp = dims.get("comprimento", 0)
                        esp = dims.get("espessura", 0)
                        if larg and comp and esp:
                            dimensoes = f"{larg}x{comp}x{esp}"
                        elif larg and comp:
                            dimensoes = f"{larg}x{comp}"
                    mini_codigo = produto.get("mini_codigo", "")
                    break
        
        # Formato antigo: procura em 'lines' usando supplier_code
        else:
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
