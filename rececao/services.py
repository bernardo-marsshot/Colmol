# rececao/services.py
import hashlib
import json
import os
import re
import base64
from io import BytesIO
from PIL import Image
import signal

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

# --- OCR.space API (Level 0 - Cloud OCR com 25k req/mês grátis) ---
try:
    import requests
    OCR_SPACE_AVAILABLE = True
except ImportError:
    OCR_SPACE_AVAILABLE = False

def ocr_space_api(file_path: str, language='por'):
    """
    OCR.space API - Level 0 (prioridade máxima)
    - 25.000 requisições/mês grátis
    - Suporta PT, ES, FR, EN + 30 idiomas
    - Detecção automática de tabelas
    - Fallback: retorna None se falhar
    """
    if not OCR_SPACE_AVAILABLE:
        return None
    
    api_key = os.environ.get('OCR_SPACE_API_KEY')
    if not api_key:
        print("⚠️ OCR_SPACE_API_KEY não encontrada - usando engines locais")
        return None
    
    try:
        url = 'https://api.ocr.space/parse/image'
        
        # Mapeamento de idiomas (por=português, spa=espanhol, fre=francês)
        lang_map = {'por': 'por', 'pt': 'por', 'es': 'spa', 'spa': 'spa', 'fr': 'fre', 'fre': 'fre', 'en': 'eng'}
        ocr_language = lang_map.get(language.lower(), 'por')
        
        with open(file_path, 'rb') as f:
            payload = {
                'apikey': api_key,
                'language': ocr_language,
                'isOverlayRequired': False,
                'detectOrientation': True,
                'scale': True,
                'OCREngine': 2,  # Engine 2 é mais preciso para tabelas
                'isTable': True  # Detecção de tabelas ativada
            }
            
            response = requests.post(url, files={'file': f}, data=payload, timeout=30)
            
            if response.status_code == 200:
                result = response.json()
                
                if result.get('IsErroredOnProcessing'):
                    print(f"⚠️ OCR.space error: {result.get('ErrorMessage', 'Unknown error')}")
                    return None
                
                # Extrai texto de todas as páginas
                text_parts = []
                if result.get('ParsedResults'):
                    for page in result['ParsedResults']:
                        page_text = page.get('ParsedText', '')
                        if page_text:
                            text_parts.append(page_text)
                
                full_text = '\n'.join(text_parts)
                
                if full_text.strip():
                    print(f"✅ OCR.space (API): {len(full_text)} chars extraídos")
                    return full_text
                else:
                    print("⚠️ OCR.space retornou texto vazio - fallback para engines locais")
                    return None
            else:
                print(f"⚠️ OCR.space HTTP {response.status_code} - fallback para engines locais")
                return None
                
    except requests.Timeout:
        print("⚠️ OCR.space timeout (30s) - fallback para engines locais")
        return None
    except Exception as e:
        print(f"⚠️ OCR.space exception: {e} - fallback para engines locais")
        return None

# --- Imports opcionais para extração universal ---
try:
    import pdfplumber
    PDFPLUMBER_AVAILABLE = True
except ImportError:
    PDFPLUMBER_AVAILABLE = False

try:
    import camelot
    CAMELOT_AVAILABLE = True
except ImportError:
    CAMELOT_AVAILABLE = False

try:
    from rapidfuzz import fuzz, process
    RAPIDFUZZ_AVAILABLE = True
except ImportError:
    RAPIDFUZZ_AVAILABLE = False

# --- PaddleOCR (lazy loading para evitar problemas no startup) ---
_paddle_ocr_instance = None

def get_paddle_ocr():
    """Inicializa PaddleOCR lazy - só quando necessário."""
    global _paddle_ocr_instance
    if _paddle_ocr_instance is None:
        try:
            from paddleocr import PaddleOCR
            _paddle_ocr_instance = PaddleOCR(use_angle_cls=True, lang='pt')
            print("✅ PaddleOCR inicializado (português)")
        except Exception as e:
            print(f"⚠️ PaddleOCR não disponível: {e}")
            _paddle_ocr_instance = False
    return _paddle_ocr_instance if _paddle_ocr_instance is not False else None

# --- EasyOCR (lazy loading para evitar problemas no startup) ---
_easyocr_instance = None

def get_easy_ocr():
    """Inicializa EasyOCR lazy - só quando necessário."""
    global _easyocr_instance
    if _easyocr_instance is None:
        try:
            import easyocr
            _easyocr_instance = easyocr.Reader(['pt', 'es', 'fr'], gpu=False)
            print("✅ EasyOCR inicializado (PT/ES/FR)")
        except Exception as e:
            print(f"⚠️ EasyOCR não disponível: {e}")
            _easyocr_instance = False
    return _easyocr_instance if _easyocr_instance is not False else None

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
    """OCR usando Tesseract. Extrai texto e faz parse para estrutura."""
    text_content = ""
    qr_codes = []
    ext = os.path.splitext(file_path)[1].lower()

    print(f"🔍 Processando com Tesseract: {os.path.basename(file_path)}")
    
    if ext == ".pdf":
        text_content, qr_codes = extract_text_from_pdf(file_path)
    elif ext in [".jpg", ".jpeg", ".png", ".tiff", ".bmp"]:
        text_content, qr_codes = extract_text_from_image(file_path)

    # Validação antecipada: se texto muito curto, pode ser ficheiro ilegível/desformatado
    texto_pdfplumber_curto = len(text_content) < 50
    if texto_pdfplumber_curto:
        print(f"⚠️ Texto pdfplumber muito curto ({len(text_content)} chars) - possível ficheiro ilegível")

    preview = "\n".join(text_content.splitlines()[:60])
    print("---- OCR PREVIEW (primeiras linhas) ----")
    print(preview)
    print("----------------------------------------")

    if qr_codes:
        print(f"✅ {len(qr_codes)} QR code(s) detectado(s)")

    if not text_content.strip():
        print("❌ OCR vazio")
        error_result = {
            "error": "OCR failed - no text extracted from document",
            "numero_requisicao": f"ERROR-{os.path.basename(file_path)}",
            "document_number": "",
            "po_number": "",
            "supplier_name": "",
            "delivery_date": "",
            "qr_codes": qr_codes,
            "lines": [],
            "totals": {
                "total_lines": 0,
                "total_quantity": 0
            },
        }
        save_extraction_to_json(error_result)
        return error_result

    result = parse_portuguese_document(text_content, qr_codes, texto_pdfplumber_curto, file_path=file_path)
    save_extraction_to_json(result)
    return result


def extract_text_from_pdf(file_path: str):
    """
    Cascata de extração de PDF (4 níveis):
    1. Texto embutido (PyPDF2) - mais rápido
    2. OCR.space API - cloud, preciso, grátis 25k/mês
    3. PaddleOCR/EasyOCR/Tesseract - local, offline
    """
    try:
        # LEVEL 1: Tenta texto embutido primeiro (mais rápido)
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

        # LEVEL 2: OCR.space API (cloud, grátis, preciso)
        print("📄 PDF sem texto embutido - tentando OCR.space API...")
        ocr_text = ocr_space_api(file_path, language='por')
        
        if ocr_text and len(ocr_text.strip()) > 50:
            # QR codes (se disponível)
            qr_codes = []
            if QR_CODE_ENABLED:
                try:
                    print("🔍 Procurando QR codes no PDF...")
                    pages = convert_from_path(file_path, dpi=300)
                    for page_num, page_img in enumerate(pages, start=1):
                        page_qr = detect_and_read_qrcodes(page_img, page_number=page_num)
                        qr_codes.extend(page_qr)
                except Exception as e:
                    print(f"⚠️ Erro ao buscar QR codes: {e}")
            return ocr_text.strip(), qr_codes

        # LEVEL 3: Engines locais (PaddleOCR → EasyOCR → Tesseract)
        print("📄 OCR.space falhou - usando engines locais (PaddleOCR/EasyOCR/Tesseract)...")
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
    """Converte todas as páginas para imagem e aplica PaddleOCR (ou Tesseract como fallback)."""
    import time
    import numpy as np
    try:
        # Tenta usar PaddleOCR primeiro
        paddle_ocr = get_paddle_ocr()
        ocr_engine = "PaddleOCR" if paddle_ocr else "Tesseract"
        
        print(f"📄 Converter PDF → imagens (OCR com {ocr_engine})…")
        
        # Converter PDF → imagens primeiro
        start_time = time.time()
        pages = convert_from_path(file_path, dpi=300)  # DPI 300 para melhor qualidade
        conversion_time = time.time() - start_time
        
        # Se conversão demorou muito (>20s), ficheiro pode ter problemas
        if conversion_time > 20:
            print(f"⚠️ Conversão PDF demorou {conversion_time:.1f}s - possível ficheiro problemático")
        
        all_text = ""
        all_qr_codes = []
        
        for i, page in enumerate(pages, 1):
            print(f"🔍 Página {i}/{len(pages)} - {ocr_engine}")
            
            # Limite de tempo por página: 15 segundos
            page_start = time.time()
            
            qr_codes = detect_and_read_qrcodes(page, page_number=i)
            all_qr_codes.extend(qr_codes)
            
            # OCR da página - cascata de 3 níveis
            page_text = ""
            paddle_failed = False
            easy_failed = False
            ocr_engine_used = None
            
            try:
                # Nível 1: PaddleOCR (rápido e preciso)
                if paddle_ocr:
                    try:
                        img_array = np.array(page)
                        result = paddle_ocr.ocr(img_array, cls=True)
                        
                        if result and result[0]:
                            for line in result[0]:
                                if line and len(line) >= 2:
                                    text = line[1][0]
                                    confidence = line[1][1]
                                    if confidence > 0.5:
                                        page_text += text + "\n"
                        
                        if page_text.strip():
                            ocr_engine_used = "PaddleOCR"
                        else:
                            paddle_failed = True
                            print(f"⚠️ PaddleOCR não extraiu texto da página {i}, tentando EasyOCR...")
                    except Exception as paddle_error:
                        paddle_failed = True
                        print(f"⚠️ PaddleOCR falhou na página {i}: {paddle_error}, tentando EasyOCR...")
                
                # Nível 2: EasyOCR (se PaddleOCR falhou)
                if (not paddle_ocr or paddle_failed) and not page_text.strip():
                    easy_ocr = get_easy_ocr()
                    if easy_ocr:
                        try:
                            import numpy as np
                            img_array = np.array(page)
                            result = easy_ocr.readtext(img_array)
                            
                            if result:
                                for detection in result:
                                    text = detection[1]
                                    confidence = detection[2]
                                    if confidence > 0.3:
                                        page_text += text + " "
                                page_text = page_text.strip() + "\n"
                            
                            if page_text.strip():
                                ocr_engine_used = "EasyOCR"
                            else:
                                easy_failed = True
                                print(f"⚠️ EasyOCR não extraiu texto da página {i}, tentando Tesseract...")
                        except Exception as easy_error:
                            easy_failed = True
                            print(f"⚠️ EasyOCR falhou na página {i}: {easy_error}, tentando Tesseract...")
                
                # Nível 3: Tesseract (fallback final)
                if not page_text.strip():
                    page_text = pytesseract.image_to_string(
                        page, config="--psm 3 --oem 3 -l por", lang="por", timeout=60)
                    if page_text.strip():
                        ocr_engine_used = "Tesseract"
                
                if page_text.strip():
                    all_text += f"\n--- Página {i} ---\n{page_text}\n"
                    if ocr_engine_used:
                        print(f"✅ Página {i} processada com {ocr_engine_used}")
                    
            except RuntimeError as e:
                if "timeout" in str(e).lower():
                    print(f"⚠️ Timeout OCR na página {i} - imagem de má qualidade")
                else:
                    raise
            except Exception as e:
                print(f"⚠️ Erro OCR na página {i}: {e}")
            
            page_time = time.time() - page_start
            if page_time > 10:
                print(f"⚠️ Página {i} demorou {page_time:.1f}s - qualidade baixa")
        
        print(f"✅ OCR completo: {len(pages)} páginas")
        return all_text.strip(), all_qr_codes
    except Exception as e:
        print(f"❌ OCR PDF erro: {e}")
        return "", []


def extract_text_from_image(file_path: str):
    """OCR para imagem com cascata de 3 níveis: PaddleOCR → EasyOCR → Tesseract."""
    import numpy as np
    try:
        img = Image.open(file_path)
        qr_codes = detect_and_read_qrcodes(img)
        
        ocr_text = ""
        paddle_failed = False
        easy_failed = False
        ocr_engine_used = None
        
        # Nível 1: PaddleOCR (rápido e preciso)
        paddle_ocr = get_paddle_ocr()
        if paddle_ocr:
            try:
                img_array = np.array(img)
                result = paddle_ocr.ocr(img_array, cls=True)
                
                if result and result[0]:
                    for line in result[0]:
                        if line and len(line) >= 2:
                            text = line[1][0]
                            confidence = line[1][1]
                            if confidence > 0.5:
                                ocr_text += text + "\n"
                
                if ocr_text.strip():
                    ocr_engine_used = "PaddleOCR"
                else:
                    paddle_failed = True
                    print(f"⚠️ PaddleOCR não extraiu texto da imagem, tentando EasyOCR...")
            except Exception as paddle_error:
                paddle_failed = True
                print(f"⚠️ PaddleOCR falhou: {paddle_error}, tentando EasyOCR...")
        
        # Nível 2: EasyOCR (se PaddleOCR falhou)
        if (not paddle_ocr or paddle_failed) and not ocr_text.strip():
            easy_ocr = get_easy_ocr()
            if easy_ocr:
                try:
                    img_array = np.array(img)
                    result = easy_ocr.readtext(img_array)
                    
                    if result:
                        for detection in result:
                            text = detection[1]
                            confidence = detection[2]
                            if confidence > 0.3:
                                ocr_text += text + " "
                        ocr_text = ocr_text.strip() + "\n"
                    
                    if ocr_text.strip():
                        ocr_engine_used = "EasyOCR"
                    else:
                        easy_failed = True
                        print(f"⚠️ EasyOCR não extraiu texto da imagem, tentando Tesseract...")
                except Exception as easy_error:
                    easy_failed = True
                    print(f"⚠️ EasyOCR falhou: {easy_error}, tentando Tesseract...")
        
        # Nível 3: Tesseract (fallback final)
        if not ocr_text.strip():
            ocr_text = pytesseract.image_to_string(img,
                                                   config="--psm 6 --oem 3 -l por",
                                                   lang="por")
            if ocr_text.strip():
                ocr_engine_used = "Tesseract"
        
        if ocr_engine_used:
            print(f"✅ Imagem processada com {ocr_engine_used}")
        
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


def detect_document_type(text: str):
    """Detecta automaticamente o tipo de documento português, francês e espanhol."""
    text_lower = text.lower()
    
    # Documentos espanhóis
    if ("pedido" in text_lower and ("españa" in text_lower or "spain" in text_lower)) or \
       ("pedido" in text_lower and any(kw in text_lower for kw in ["artículo", "articulo", "descripción", "descripcion", "unidades", "cantidad"])):
        return "PEDIDO_ESPANHOL"
    
    # Documentos franceses
    if "bon de commande" in text_lower or ("commande" in text_lower and "désignation" in text_lower):
        return "BON_COMMANDE"
    
    # Documentos portugueses
    if "ordem compra" in text_lower or "ordem de compra" in text_lower:
        return "ORDEM_COMPRA"
    elif "elastron" in text_lower and "fatura" in text_lower:
        return "FATURA_ELASTRON"
    elif "colmol" in text_lower and ("guia" in text_lower or "comunicação de saída" in text_lower):
        return "GUIA_COLMOL"
    elif "fatura" in text_lower or "ft" in text_lower:
        return "FATURA_GENERICA"
    elif "guia de remessa" in text_lower or "guia remessa" in text_lower:
        return "GUIA_GENERICA"
    elif "recibo" in text_lower or "receipt" in text_lower:
        return "RECIBO"
    else:
        return "DOCUMENTO_GENERICO"


def parse_fatura_elastron(text: str):
    """Parser específico para faturas Elastron (compatível com Tesseract)."""
    produtos = []
    lines = text.split("\n")
    
    current_ref = ""
    for i, line in enumerate(lines):
        line_stripped = line.strip()
        
        if re.match(r'^\d[A-Z]{4}\s+[NnºN]', line_stripped):
            current_ref = line_stripped
            continue
        
        artigo_match = re.match(r'^(E[O0]\d{9,10})\s+(.+)', line_stripped)
        if artigo_match:
            try:
                artigo = artigo_match.group(1).replace('O', '0')
                resto = artigo_match.group(2).strip()
                
                parts = resto.split()
                if len(parts) < 6:
                    continue
                
                # Tesseract format: TOTAL VOL QUANT DESC UNID PRECO IVA LOTE... DESCRICAO
                # Encontrar unidade (ML, MT, UN)
                unidade_idx = -1
                unidade = "ML"
                for idx, part in enumerate(parts):
                    if part.upper() in ['ML', 'MT', 'UN', 'M²', 'M2']:
                        unidade = part.upper()
                        unidade_idx = idx
                        break
                
                if unidade_idx < 3:
                    continue
                
                # Campos antes da unidade: TOTAL VOL QUANT DESC
                total = float(parts[0].replace(',', '.'))
                volume = int(parts[1]) if parts[1].isdigit() else 1
                quantidade = float(parts[2].replace(',', '.'))
                desconto = float(parts[3].replace(',', '.'))
                
                # Campos depois da unidade: PRECO IVA LOTE ... DESCRICAO
                preco_un = float(parts[unidade_idx + 1].replace(',', '.')) if unidade_idx + 1 < len(parts) else 0.0
                iva = float(parts[unidade_idx + 2].replace(',', '.')) if unidade_idx + 2 < len(parts) else 23.0
                
                # Lote e descrição
                lote = ""
                descricao = ""
                if unidade_idx + 3 < len(parts):
                    remaining = ' '.join(parts[unidade_idx + 3:])
                    lote_match = re.search(r'(\d{4}-\d+(?:#)?)', remaining)
                    if lote_match:
                        lote = lote_match.group(1)
                        descricao = remaining[lote_match.end():].strip()
                    else:
                        descricao = remaining
                
                produtos.append({
                    "referencia_ordem": current_ref,
                    "artigo": artigo,
                    "descricao": descricao,
                    "lote_producao": lote,
                    "quantidade": quantidade,
                    "unidade": unidade,
                    "volume": volume,
                    "preco_unitario": preco_un,
                    "desconto": desconto,
                    "iva": iva,
                    "total": total
                })
            except (ValueError, IndexError) as e:
                print(f"⚠️ Erro ao parsear linha Elastron '{line_stripped[:60]}': {e}")
                continue
    
    return produtos


def parse_guia_colmol(text: str):
    """Parser específico para Guias de Remessa Colmol."""
    produtos = []
    lines = text.split("\n")
    
    current_encomenda = ""
    current_requisicao = ""
    
    for i, line in enumerate(lines):
        line_stripped = line.strip()
        
        if "ENCOMENDA Nº" in line_stripped:
            encomenda_match = re.search(r'ENCOMENDA Nº\.?\s*(\d+-\d+)', line_stripped)
            requisicao_match = re.search(r'REQUISICAO Nº\.?\s*(\d+)', line_stripped)
            if encomenda_match:
                current_encomenda = encomenda_match.group(1)
            if requisicao_match:
                current_requisicao = requisicao_match.group(1)
            continue
        
        if re.match(r'^[A-Z0-9]{10,}', line_stripped):
            parts = line_stripped.split()
            if len(parts) >= 8:
                try:
                    codigo = parts[0]
                    
                    descricao_parts = []
                    j = 1
                    # Parar na descrição quando encontrar: número decimal, unidade (UN/MT/ML), ou padrão CX.
                    while j < len(parts):
                        part = parts[j]
                        # Número decimal (quantidade)
                        if re.match(r'^\d+[.,]\d+$', part):
                            break
                        # Unidades conhecidas (às vezes vem antes da quantidade)
                        if part.upper() in ['UN', 'MT', 'ML', 'M²', 'M2']:
                            break
                        # Padrão de dimensões (CX.1150x...)
                        if re.match(r'^CX\.\d', part, re.IGNORECASE):
                            descricao_parts.append(part)
                            j += 1
                            break
                        descricao_parts.append(part)
                        j += 1
                    
                    descricao = ' '.join(descricao_parts)
                    
                    # Agora procurar quantidade (pode ter espaços antes)
                    while j < len(parts) and not re.match(r'^\d+[.,]\d+$', parts[j]):
                        j += 1
                    
                    quantidade = float(parts[j].replace(',', '.')) if j < len(parts) else 0.0
                    unidade = parts[j+1] if j+1 < len(parts) else "UN"
                    med1 = float(parts[j+2].replace(',', '.')) if j+2 < len(parts) else 0.0
                    med2 = float(parts[j+3].replace(',', '.')) if j+3 < len(parts) else 0.0
                    med3 = float(parts[j+4].replace(',', '.')) if j+4 < len(parts) else 0.0
                    peso = float(parts[j+5].replace(',', '.')) if j+5 < len(parts) else 0.0
                    iva = float(parts[j+6].replace(',', '.')) if j+6 < len(parts) else 23.0
                    
                    produtos.append({
                        "referencia_ordem": f"{current_encomenda} / Req {current_requisicao}",
                        "artigo": codigo,
                        "descricao": descricao,
                        "lote_producao": "",
                        "quantidade": quantidade,
                        "unidade": unidade,
                        "volume": 0,
                        "dimensoes": f"{med1}x{med2}x{med3}",
                        "peso": peso,
                        "iva": iva,
                        "total": 0.0
                    })
                except (ValueError, IndexError) as e:
                    print(f"⚠️ Erro ao parsear linha Colmol: {e}")
                    continue
    
    return produtos


def parse_guia_generica(text: str):
    """
    Parser genérico para extrair produtos de qualquer formato de guia de remessa.
    Usa heurísticas para detectar tabelas com produtos.
    """
    produtos = []
    lines = text.split("\n")
    
    pedido_atual = ""
    
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or len(stripped) < 10:
            continue
        
        pedido_match = re.search(r'(?:PEDIDO|ORDER|ENCOMENDA)\s*[:/]?\s*(\d+)', stripped, re.IGNORECASE)
        if pedido_match:
            pedido_atual = pedido_match.group(1)
            continue
        
        produto_match = re.match(
            r'^([A-Z0-9]{8,})\s+'
            r'(.+?)\s+'
            r'([\d,\.]+)\s+'
            r'([A-Z]{2,4})(?:\s|$)',
            stripped,
            re.IGNORECASE
        )
        
        if produto_match:
            codigo = produto_match.group(1).strip()
            descricao = produto_match.group(2).strip()
            quantidade_str = produto_match.group(3).strip()
            unidade = produto_match.group(4).strip().upper()
            
            try:
                if ',' in quantidade_str:
                    quantidade = float(quantidade_str.replace('.', '').replace(',', '.'))
                else:
                    quantidade = float(quantidade_str.replace(',', ''))
            except ValueError:
                continue
            
            dims = ""
            dim_match = re.search(r'(\d{3,4})[xX×](\d{3,4})[xX×](\d{3,4})', descricao)
            if dim_match:
                dims = f"{float(dim_match.group(1))/1000:.2f}x{float(dim_match.group(2))/1000:.2f}x{float(dim_match.group(3))/1000:.2f}"
            
            produtos.append({
                "referencia_ordem": pedido_atual or "",
                "artigo": codigo,
                "descricao": descricao,
                "lote_producao": "",
                "quantidade": quantidade,
                "unidade": unidade,
                "volume": 0,
                "dimensoes": dims,
                "peso": 0.0,
                "iva": 23.0,
                "total": 0.0
            })
    
    return produtos


def parse_ordem_compra(text: str):
    """
    Parser específico para Ordens de Compra com linhas separadas.
    Formato: Referência + Descrição numa linha, Quantidade + Unidade + Data noutra linha.
    """
    produtos = []
    lines = text.split("\n")
    
    # Encontrar referências de produtos
    referencias = []
    quantidades = []
    
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        
        # Detectar linha de quantidade + unidade PRIMEIRO (mais específico)
        # Formato: 1.000 UN 2025-10-17 [texto opcional]
        # Aceita: uppercase/lowercase units, data opcional, texto trailing opcional
        # Exemplo: "1.000 UN 2025-10-17", "1.000 un", "3.5 KG 2025-10-17 RECEBIDO"
        qty_match = re.match(r'^([\d,\.]+)\s+([A-Za-z]{2,4})(?:\s+(\d{4}-\d{2}-\d{2}))?', stripped)
        if qty_match:
            quantidade_str = qty_match.group(1)
            unidade = qty_match.group(2).upper()
            data_entrega = qty_match.group(3) if qty_match.group(3) else ""
            
            # Validar unidade: lista de unidades conhecidas OU tem data (evita false positives)
            unidades_validas = {'UN', 'UNI', 'UNID', 'PC', 'PCS', 'KG', 'G', 'M', 'M2', 'M3', 'L', 'ML', 'CX', 'PAR', 'PAC', 'SET', 'RL', 'FD'}
            is_valid_unit = unidade in unidades_validas or data_entrega
            
            if is_valid_unit:
                try:
                    # Converter quantidade (formato PT: 1.000 = 1000)
                    if '.' in quantidade_str and ',' not in quantidade_str:
                        # Formato 1.000 (mil)
                        quantidade = float(quantidade_str.replace('.', ''))
                    elif ',' in quantidade_str:
                        # Formato 1,5 (um e meio)
                        quantidade = float(quantidade_str.replace(',', '.'))
                    else:
                        quantidade = float(quantidade_str)
                        
                    quantidades.append({
                        'quantidade': quantidade,
                        'unidade': unidade,
                        'data_entrega': data_entrega
                    })
                    continue
                except ValueError:
                    pass
        
        # Detectar linha de referência + descrição (menos específico)
        # Formato: 26.100145 COLCHAO 1,95X1,40=27"SPA CHERRY VISCO"COLMOL
        # Só faz match se NÃO for linha de quantidade (já verificado acima)
        ref_match = re.match(r'^(\d+\.\d+)\s+(.+)$', stripped)
        if ref_match:
            referencias.append({
                'codigo': ref_match.group(1),
                'descricao': ref_match.group(2).strip()
            })
            continue
    
    # Validar emparelhamento de referências e quantidades
    if len(referencias) != len(quantidades):
        print(f"⚠️ Contagem inconsistente: {len(referencias)} referências vs {len(quantidades)} quantidades")
        print(f"   Referências: {[r['codigo'] for r in referencias]}")
        qtys_str = ["{} {}".format(q['quantidade'], q['unidade']) for q in quantidades]
        print(f"   Quantidades: {qtys_str}")
        # Usar o mínimo para evitar IndexError
        min_count = min(len(referencias), len(quantidades))
        print(f"   Processando apenas {min_count} produtos emparelhados")
    
    # Combinar referências com quantidades (ordem sequencial 1:1)
    paired_count = min(len(referencias), len(quantidades))
    for i in range(paired_count):
        ref = referencias[i]
        if i < len(quantidades):
            qty_info = quantidades[i]
            
            # Extrair dimensões da descrição se existirem
            dims = ""
            dim_match = re.search(r'(\d),(\d{2})[xX×](\d),(\d{2})', ref['descricao'])
            if dim_match:
                dims = f"{dim_match.group(1)}.{dim_match.group(2)}x{dim_match.group(3)}.{dim_match.group(4)}"
            
            produtos.append({
                "artigo": ref['codigo'],
                "descricao": ref['descricao'],
                "quantidade": qty_info['quantidade'],
                "unidade": qty_info['unidade'],
                "data_entrega": qty_info['data_entrega'],
                "dimensoes": dims,
                "referencia_ordem": "",
                "lote_producao": "",
                "volume": 0,
                "peso": 0.0,
                "iva": 23.0,
                "total": 0.0
            })
    
    return produtos


def parse_bon_commande(text: str):
    """
    Parser dedicado para BON DE COMMANDE (Notas de Encomenda francesas).
    
    Formato esperado:
    Désignation  Quantité  Prix unitaire  Montant
    MATELAS SAN REMO 140x190  2 202.00€ 404.00€
    
    Extrai:
    - Referência/Designação do produto
    - Quantidade
    - Preço unitário
    - Total da linha
    """
    produtos = []
    lines = text.split("\n")
    
    # Buscar cliente
    cliente = ""
    cliente_match = re.search(r'ADRESSE DE LIVRAISON\s+([^\n]+)', text, re.IGNORECASE)
    if cliente_match:
        cliente = cliente_match.group(1).strip()
    
    # Buscar data
    data = ""
    data_match = re.search(r'DATE\s*:\s*(\d{2}\.\d{2}\.\d{2})', text, re.IGNORECASE)
    if data_match:
        data = data_match.group(1)
    
    # Buscar contremarque
    contremarque = ""
    cm_match = re.search(r'CONTREMARQUE\s*:\s*([^\n]+)', text, re.IGNORECASE)
    if cm_match:
        contremarque = cm_match.group(1).strip()
    
    in_product_section = False
    
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        
        # Detectar início da seção de produtos
        if re.search(r'Désignation.*Quantité.*Prix', stripped, re.IGNORECASE):
            in_product_section = True
            continue
        
        # Detectar fim da seção (TOTAL ou endereço)
        if re.search(r'^TOTAL|^ADRESSE|^BON DE COMMANDE', stripped, re.IGNORECASE):
            in_product_section = False
            continue
        
        if in_product_section:
            # Formato: MATELAS SAN REMO 140x190  2 202.00€ 404.00€
            # Produto pode ter dimensões (140x190, 180x200, etc)
            # Quantidade é número inteiro
            # Preços em formato europeu (202.00€)
            
            # Padrão: [PRODUTO com possíveis dimensões] [QTY] [PREÇO€] [TOTAL€]
            match = re.match(
                r'^(.+?)\s+(\d+)\s+([\d,\.]+)\s*€\s+([\d,\.]+)\s*€',
                stripped
            )
            
            if match:
                designacao = match.group(1).strip()
                quantidade = int(match.group(2))
                preco_str = match.group(3).replace(',', '.')
                total_str = match.group(4).replace(',', '.')
                
                try:
                    preco_unitario = float(preco_str)
                    total_linha = float(total_str)
                    
                    # Extrair dimensões da designação se existirem
                    dims = ""
                    dim_match = re.search(r'(\d{2,3})\s*[xX×]\s*(\d{2,3})', designacao)
                    if dim_match:
                        dims = f"{dim_match.group(1)}x{dim_match.group(2)}"
                    
                    # Extrair código/referência se existir (formato tipo SAN REMO, RIVIERA)
                    codigo = ""
                    cod_match = re.match(r'^([A-Z\s]+?)\s+\d', designacao)
                    if cod_match:
                        codigo = cod_match.group(1).strip()
                    
                    produtos.append({
                        "artigo": codigo if codigo else designacao[:20],
                        "descricao": designacao,
                        "quantidade": float(quantidade),
                        "unidade": "UN",
                        "preco_unitario": preco_unitario,
                        "total": total_linha,
                        "dimensoes": dims,
                        "cliente": cliente,
                        "data_encomenda": data,
                        "contremarque": contremarque,
                        "referencia_ordem": "",
                        "lote_producao": "",
                        "volume": 0,
                        "peso": 0.0,
                        "iva": 20.0  # IVA França padrão
                    })
                except ValueError as e:
                    print(f"⚠️ Erro ao converter valores numéricos em '{stripped[:50]}': {e}")
                    continue
    
    return produtos


def parse_pedido_espanhol(text: str):
    """
    Parser dedicado para PEDIDO espanhol (NATURCOLCHON, COSGUI, etc).
    
    Formatos esperados:
    1. NATURCOLCHON: Código | Descripción | Unidades | Precio | Importe
       COPR1520 COLCHON PRAGA DE 150X200 CM 5,00 175,00 875,00
    
    2. COSGUI: Código | Descripción | Cantidad
       LUSTOPVS135190 COLCHON TOP VISCO 2019 135X190 4,00
    """
    produtos = []
    lines = text.split("\n")
    
    # Buscar número de pedido
    pedido_num = ""
    ped_match = re.search(r'(?:Pedido|Número).*?(\d+)', text, re.IGNORECASE)
    if ped_match:
        pedido_num = ped_match.group(1)
    
    # Buscar data
    fecha = ""
    fecha_match = re.search(r'Fecha.*?(\d{2}/\d{2}/\d{4})', text, re.IGNORECASE)
    if fecha_match:
        fecha = fecha_match.group(1)
    
    # Buscar proveedor
    proveedor = ""
    prov_match = re.search(r'Proveedor.*?([A-Z\s\.]+)', text, re.IGNORECASE)
    if prov_match:
        proveedor = prov_match.group(1).strip()
    
    in_product_section = False
    
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        
        # Detectar início da seção de produtos (keywords podem vir em linhas separadas)
        if re.search(r'Artículo|Descripción|Cantidad', stripped, re.IGNORECASE):
            in_product_section = True
            continue
        
        # Detectar fim da seção
        if re.search(r'^Total|^Importe neto|^Notas|^Plazo|^Base I\.V\.A', stripped, re.IGNORECASE):
            in_product_section = False
            continue
        
        if in_product_section:
            # Formato 1B: DESCRIPCIÓN CÓDIGO TOTAL PRECIO UNIDADES (formato invertido NATURCOLCHON)
            # Exemplo: COLCHON PRAGA DE 150X200 CM*NUEVO* COPR1520 875,00 175,00 5,00
            # VERIFICAR PRIMEIRO pois tem 3 números (mais específico)
            match1b = re.match(
                r'^(.+?)\s+([A-Z0-9]{4,})\s+([\d,]+)\s+([\d,]+)\s+([\d,]+)$',
                stripped
            )
            
            # Formato 1: CÓDIGO DESCRIPCIÓN UNIDADES PRECIO IMPORTE
            # Exemplo: COPR1520 COLCHON PRAGA DE 150X200 CM*NUEVO* 5,00 175,00 875,00
            match1 = re.match(
                r'^([A-Z0-9]{4,})\s+(.+?)\s+([\d,]+)\s+([\d,]+)\s+([\d,]+)$',
                stripped
            )
            
            if match1b:
                # Formato invertido: descrição vem primeiro
                descripcion = match1b.group(1).strip()
                codigo = match1b.group(2)
                total_str = match1b.group(3).replace(',', '.')
                precio_str = match1b.group(4).replace(',', '.')
                cantidad_str = match1b.group(5).replace(',', '.')
                
                try:
                    cantidad = float(cantidad_str)
                    precio = float(precio_str)
                    total = float(total_str)
                    
                    # Extrair dimensões
                    dims = ""
                    dim_match = re.search(r'(\d{2,3})[xX×](\d{2,3})', descripcion)
                    if dim_match:
                        dims = f"{dim_match.group(1)}x{dim_match.group(2)}"
                    
                    produtos.append({
                        "artigo": codigo,
                        "descricao": descripcion,
                        "quantidade": cantidad,
                        "unidade": "UN",
                        "preco_unitario": precio,
                        "total": total,
                        "dimensoes": dims,
                        "pedido_numero": pedido_num,
                        "fecha": fecha,
                        "proveedor": proveedor,
                        "referencia_ordem": "",
                        "lote_producao": "",
                        "volume": 0,
                        "peso": 0.0,
                        "iva": 21.0  # IVA Espanha padrão
                    })
                    continue
                except ValueError:
                    pass
            
            elif match1:
                codigo = match1.group(1)
                descripcion = match1.group(2).strip()
                cantidad_str = match1.group(3).replace(',', '.')
                precio_str = match1.group(4).replace(',', '.')
                total_str = match1.group(5).replace(',', '.')
                
                try:
                    cantidad = float(cantidad_str)
                    precio = float(precio_str)
                    total = float(total_str)
                    
                    # Extrair dimensões
                    dims = ""
                    dim_match = re.search(r'(\d{2,3})[xX×](\d{2,3})', descripcion)
                    if dim_match:
                        dims = f"{dim_match.group(1)}x{dim_match.group(2)}"
                    
                    produtos.append({
                        "artigo": codigo,
                        "descricao": descripcion,
                        "quantidade": cantidad,
                        "unidade": "UN",
                        "preco_unitario": precio,
                        "total": total,
                        "dimensoes": dims,
                        "pedido_numero": pedido_num,
                        "fecha": fecha,
                        "proveedor": proveedor,
                        "referencia_ordem": "",
                        "lote_producao": "",
                        "volume": 0,
                        "peso": 0.0,
                        "iva": 21.0  # IVA Espanha padrão
                    })
                    continue
                except ValueError:
                    pass
            
            # Formato 2: CÓDIGO DESCRIPCIÓN CANTIDAD
            # Exemplo: LUSTOPVS135190 COLCHON TOP VISCO 2019 135X190 4,00
            match2 = re.match(
                r'^([A-Z0-9]{6,})\s+(.+?)\s+([\d,]+)$',
                stripped
            )
            
            if match2:
                codigo = match2.group(1)
                descripcion = match2.group(2).strip()
                cantidad_str = match2.group(3).replace(',', '.')
                
                try:
                    cantidad = float(cantidad_str)
                    
                    # Extrair dimensões
                    dims = ""
                    dim_match = re.search(r'(\d{2,3})[xX×](\d{2,3})', descripcion)
                    if dim_match:
                        dims = f"{dim_match.group(1)}x{dim_match.group(2)}"
                    
                    produtos.append({
                        "artigo": codigo,
                        "descricao": descripcion,
                        "quantidade": cantidad,
                        "unidade": "UN",
                        "preco_unitario": 0.0,
                        "total": 0.0,
                        "dimensoes": dims,
                        "pedido_numero": pedido_num,
                        "fecha": fecha,
                        "proveedor": proveedor,
                        "referencia_ordem": "",
                        "lote_producao": "",
                        "volume": 0,
                        "peso": 0.0,
                        "iva": 21.0
                    })
                except ValueError:
                    pass
    
    return produtos


# ============================================================================
# FUNÇÕES UNIVERSAIS DE EXTRAÇÃO (Fuzzy Matching + Table Extraction)
# ============================================================================

def universal_kv_extract(text: str, file_path: str = None):
    """
    Extração universal de key-value pairs usando fuzzy matching (rapidfuzz).
    Encontra: fornecedor/supplier/proveedor, NIF, IBAN, número documento, data, número encomenda
    """
    if not RAPIDFUZZ_AVAILABLE:
        return {}
    
    result = {}
    lines = text.split('\n')
    
    # Sinônimos multi-idioma para campos-chave
    synonyms = {
        'fornecedor': ['fornecedor', 'supplier', 'proveedor', 'empresa', 'vendedor', 'seller', 'company'],
        'nif': ['nif', 'vat', 'nipc', 'tax id', 'cif', 'dni', 'identificação fiscal'],
        'iban': ['iban', 'account', 'conta bancária', 'bank account', 'cuenta bancaria'],
        'documento': ['documento', 'document', 'factura', 'fatura', 'invoice', 'guia', 'pedido', 'order'],
        'data': ['data', 'date', 'fecha', 'datum'],
        'encomenda': ['encomenda', 'order', 'pedido', 'purchase order', 'po', 'commande']
    }
    
    for line in lines:
        line_clean = line.strip()
        if not line_clean or len(line_clean) < 3:
            continue
        
        # Split em possível key:value
        parts = line_clean.split(':', 1)
        if len(parts) == 2:
            key_candidate = parts[0].strip().lower()
            value_candidate = parts[1].strip()
            
            # Fuzzy match para cada categoria
            for field, variants in synonyms.items():
                if field in result:  # Já encontrado
                    continue
                
                # Usa rapidfuzz para encontrar melhor match
                best_match = process.extractOne(key_candidate, variants, scorer=fuzz.ratio)
                
                if best_match and best_match[1] >= 70:  # Score >= 70%
                    result[field] = value_candidate
                    break
    
    return result


def universal_table_extract(file_path: str):
    """
    Extração universal de tabelas usando Camelot + pdfplumber.
    Retorna lista de produtos extraídos de tabelas detectadas.
    """
    produtos = []
    
    # Método 1: Camelot (melhor para tabelas com bordas)
    if CAMELOT_AVAILABLE and file_path.lower().endswith('.pdf'):
        try:
            tables = camelot.read_pdf(file_path, pages='all', flavor='lattice')
            
            if len(tables) > 0:
                print(f"✅ Camelot detectou {len(tables)} tabela(s)")
                
                for table_idx, table in enumerate(tables):
                    df = table.df
                    
                    # Tenta identificar colunas de produto (heurística)
                    possible_headers = df.iloc[0].tolist() if len(df) > 0 else []
                    header_lower = [str(h).lower() for h in possible_headers]
                    
                    # Procura colunas importantes
                    col_map = {}
                    for idx, h in enumerate(header_lower):
                        if any(kw in h for kw in ['código', 'codigo', 'code', 'ref', 'artigo', 'article']):
                            col_map['codigo'] = idx
                        elif any(kw in h for kw in ['descrição', 'descripcion', 'description', 'designation', 'produto']):
                            col_map['descricao'] = idx
                        elif any(kw in h for kw in ['quantidade', 'qty', 'qtd', 'quant', 'unidades', 'cantidad']):
                            col_map['quantidade'] = idx
                        elif any(kw in h for kw in ['preço', 'precio', 'price', 'unitário', 'unit']):
                            col_map['preco'] = idx
                    
                    # Extrai produtos
                    for row_idx in range(1, len(df)):
                        row = df.iloc[row_idx]
                        
                        produto = {}
                        if 'codigo' in col_map:
                            produto['artigo'] = str(row[col_map['codigo']]).strip()
                        if 'descricao' in col_map:
                            produto['descricao'] = str(row[col_map['descricao']]).strip()
                        if 'quantidade' in col_map:
                            qty_str = str(row[col_map['quantidade']]).strip()
                            try:
                                produto['quantidade'] = float(qty_str.replace(',', '.'))
                            except:
                                produto['quantidade'] = 0.0
                        if 'preco' in col_map:
                            preco_str = str(row[col_map['preco']]).strip()
                            try:
                                produto['preco_unitario'] = float(preco_str.replace(',', '.'))
                            except:
                                produto['preco_unitario'] = 0.0
                        
                        # Valida produto mínimo (tem código OU descrição + quantidade)
                        if (produto.get('artigo') or produto.get('descricao')) and produto.get('quantidade', 0) > 0:
                            produtos.append(produto)
        
        except Exception as e:
            print(f"⚠️ Camelot falhou: {e}")
    
    # Método 2: pdfplumber (melhor para tabelas sem bordas)
    if PDFPLUMBER_AVAILABLE and file_path.lower().endswith('.pdf') and len(produtos) == 0:
        try:
            with pdfplumber.open(file_path) as pdf:
                for page in pdf.pages:
                    tables = page.extract_tables()
                    
                    if tables:
                        print(f"✅ pdfplumber detectou {len(tables)} tabela(s) na página {page.page_number}")
                        
                        for table in tables:
                            if not table or len(table) < 2:
                                continue
                            
                            # Primeira linha = headers
                            headers = [str(h).lower().strip() if h else '' for h in table[0]]
                            
                            # Mapeia colunas
                            col_map = {}
                            for idx, h in enumerate(headers):
                                if any(kw in h for kw in ['código', 'codigo', 'code', 'ref', 'artigo']):
                                    col_map['codigo'] = idx
                                elif any(kw in h for kw in ['descrição', 'descripcion', 'description', 'designation']):
                                    col_map['descricao'] = idx
                                elif any(kw in h for kw in ['quantidade', 'qty', 'qtd', 'quant', 'unidades', 'cantidad']):
                                    col_map['quantidade'] = idx
                                elif any(kw in h for kw in ['preço', 'precio', 'price', 'unitário', 'unit']):
                                    col_map['preco'] = idx
                            
                            # Extrai linhas
                            for row in table[1:]:
                                if not row or len(row) == 0:
                                    continue
                                
                                produto = {}
                                if 'codigo' in col_map and col_map['codigo'] < len(row):
                                    produto['artigo'] = str(row[col_map['codigo']]).strip() if row[col_map['codigo']] else ''
                                if 'descricao' in col_map and col_map['descricao'] < len(row):
                                    produto['descricao'] = str(row[col_map['descricao']]).strip() if row[col_map['descricao']] else ''
                                if 'quantidade' in col_map and col_map['quantidade'] < len(row):
                                    qty_str = str(row[col_map['quantidade']]).strip() if row[col_map['quantidade']] else '0'
                                    try:
                                        produto['quantidade'] = float(qty_str.replace(',', '.'))
                                    except:
                                        produto['quantidade'] = 0.0
                                if 'preco' in col_map and col_map['preco'] < len(row):
                                    preco_str = str(row[col_map['preco']]).strip() if row[col_map['preco']] else '0'
                                    try:
                                        produto['preco_unitario'] = float(preco_str.replace(',', '.'))
                                    except:
                                        produto['preco_unitario'] = 0.0
                                
                                # Valida produto mínimo
                                if (produto.get('artigo') or produto.get('descricao')) and produto.get('quantidade', 0) > 0:
                                    produtos.append(produto)
        
        except Exception as e:
            print(f"⚠️ pdfplumber falhou: {e}")
    
    if produtos:
        print(f"✅ Extração universal de tabelas: {len(produtos)} produtos")
    
    return produtos


def parse_generic_document(text: str, file_path: str = None):
    """
    Parser genérico universal - última tentativa quando parsers específicos falharem.
    Combina regex heurísticos + table extraction + fuzzy matching.
    """
    produtos = []
    metadata = {}
    
    # 1. Extração de metadados com fuzzy matching
    if file_path:
        metadata = universal_kv_extract(text, file_path)
        print(f"📋 Metadados extraídos (fuzzy): {list(metadata.keys())}")
    
    # 2. Tentativa de extração por tabelas
    if file_path:
        produtos = universal_table_extract(file_path)
    
    # 3. Se ainda não tem produtos, tenta regex genéricos
    if len(produtos) == 0:
        lines = text.split('\n')
        
        # Regex genérico para linhas de produto (artigo + descrição + quantidade + preço)
        generic_patterns = [
            # Padrão 1: CÓDIGO DESCRIÇÃO QTY PREÇO
            r'^\s*([A-Z0-9\-]+)\s+(.{10,60}?)\s+(\d+[,.]?\d*)\s+(\d+[,.]?\d+)\s*$',
            # Padrão 2: CÓDIGO | DESCRIÇÃO | QTY
            r'^\s*([A-Z0-9\-]+)\s*\|\s*(.{10,60}?)\s*\|\s*(\d+[,.]?\d*)',
            # Padrão 3: QTY DESCRIÇÃO CÓDIGO
            r'^\s*(\d+[,.]?\d*)\s+(.{10,60}?)\s+([A-Z0-9\-]+)\s*$'
        ]
        
        for line in lines:
            line_stripped = line.strip()
            if len(line_stripped) < 10:
                continue
            
            for pattern_idx, pattern in enumerate(generic_patterns):
                match = re.match(pattern, line_stripped)
                if match:
                    try:
                        if pattern_idx == 0:  # CÓDIGO DESC QTY PREÇO
                            codigo, desc, qty, preco = match.groups()
                            produtos.append({
                                'artigo': codigo.strip(),
                                'descricao': desc.strip(),
                                'quantidade': float(qty.replace(',', '.')),
                                'preco_unitario': float(preco.replace(',', '.'))
                            })
                        elif pattern_idx == 1:  # CÓDIGO | DESC | QTY
                            codigo, desc, qty = match.groups()
                            produtos.append({
                                'artigo': codigo.strip(),
                                'descricao': desc.strip(),
                                'quantidade': float(qty.replace(',', '.')),
                                'preco_unitario': 0.0
                            })
                        elif pattern_idx == 2:  # QTY DESC CÓDIGO
                            qty, desc, codigo = match.groups()
                            produtos.append({
                                'artigo': codigo.strip(),
                                'descricao': desc.strip(),
                                'quantidade': float(qty.replace(',', '.')),
                                'preco_unitario': 0.0
                            })
                        break  # Encontrou match, próxima linha
                    except ValueError:
                        continue
    
    if produtos:
        print(f"✅ Parser genérico universal: {len(produtos)} produtos extraídos")
    else:
        print("⚠️ Parser genérico universal: 0 produtos extraídos")
    
    return {'produtos': produtos, 'metadata': metadata}


def parse_portuguese_document(text: str, qr_codes=None, texto_pdfplumber_curto=False, file_path=None):
    """
    Extrai cabeçalho (req/doc/fornecedor/data) e linhas de produto.
    Usa fallback universal (fuzzy matching + table extraction) se parsers específicos falharem.
    """
    if qr_codes is None:
        qr_codes = []
    
    doc_type = detect_document_type(text)
    print(f"📄 Tipo de documento detectado: {doc_type}")

    lines = text.split("\n")
    result = {
        "numero_requisicao": "",
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
        "tipo_documento": doc_type,
        "texto_completo": text,
        "baixa_qualidade_texto": texto_pdfplumber_curto,
    }

    patterns = {
        "req": r"(?:req|requisição)\.?\s*n?[oº]?\s*:?\s*([A-Z0-9\-/]+)",
        "doc": r"(?:guia|gr|documento|fatura)\.?\s*n?[oº]?\s*:?\s*([A-Z0-9\-/]+)",
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

        if not result["delivery_date"]:
            m = re.search(patterns["data"], ln)
            if m:
                result["delivery_date"] = m.group(1)

        if not result["supplier_name"]:
            m = re.search(patterns["fornecedor"], low)
            if m:
                result["supplier_name"] = m.group(1).title()

    if doc_type == "PEDIDO_ESPANHOL":
        produtos = parse_pedido_espanhol(text)
        if produtos:
            result["produtos"] = produtos
            print(f"✅ Extraídos {len(produtos)} produtos do Pedido Espanhol")
            
            # Extrair metadados dos produtos
            if produtos and produtos[0].get("proveedor"):
                result["supplier_name"] = produtos[0]["proveedor"]
            if produtos and produtos[0].get("fecha"):
                result["delivery_date"] = produtos[0]["fecha"]
            if produtos and produtos[0].get("pedido_numero"):
                result["document_number"] = produtos[0]["pedido_numero"]
        else:
            print("⚠️ Parser Pedido Espanhol retornou 0 produtos")
    elif doc_type == "BON_COMMANDE":
        produtos = parse_bon_commande(text)
        if produtos:
            result["produtos"] = produtos
            print(f"✅ Extraídos {len(produtos)} produtos do Bon de Commande")
            
            # Extrair cliente e data dos produtos
            if produtos and produtos[0].get("cliente"):
                result["supplier_name"] = produtos[0]["cliente"]
            if produtos and produtos[0].get("data_encomenda"):
                result["delivery_date"] = produtos[0]["data_encomenda"]
            
            # Extrair contremarque como número de documento
            if produtos and produtos[0].get("contremarque"):
                result["document_number"] = produtos[0]["contremarque"]
        else:
            print("⚠️ Parser Bon de Commande retornou 0 produtos")
    elif doc_type == "ORDEM_COMPRA":
        produtos = parse_ordem_compra(text)
        if produtos:
            result["produtos"] = produtos
            print(f"✅ Extraídos {len(produtos)} produtos da Ordem de Compra")
            
            # Extrair número da ordem de compra
            oc_match = re.search(r'ORDEM\s+COMPRA\s+N[ºo]?\s*([A-Z0-9]+)', text, re.IGNORECASE)
            if oc_match:
                result["po_number"] = oc_match.group(1)
                result["document_number"] = oc_match.group(1)
        else:
            print("⚠️ Parser Ordem de Compra retornou 0 produtos")
    elif doc_type == "FATURA_ELASTRON":
        produtos = parse_fatura_elastron(text)
        if produtos:
            result["produtos"] = produtos
            result["supplier_name"] = "Elastron Portugal, SA"
            print(f"✅ Extraídos {len(produtos)} produtos da Fatura Elastron")
        else:
            print("⚠️ Parser Elastron retornou 0 produtos, tentando parser genérico...")
            produtos = parse_guia_generica(text)
            if produtos:
                result["produtos"] = produtos
                print(f"✅ Extraídos {len(produtos)} produtos com parser genérico")
    elif doc_type == "GUIA_COLMOL":
        produtos = parse_guia_colmol(text)
        if produtos:
            result["produtos"] = produtos
            result["supplier_name"] = "Colmol - Colchões S.A"
            print(f"✅ Extraídos {len(produtos)} produtos da Guia Colmol")
        else:
            print("⚠️ Parser Colmol retornou 0 produtos, tentando parser genérico...")
            produtos = parse_guia_generica(text)
            if produtos:
                result["produtos"] = produtos
                print(f"✅ Extraídos {len(produtos)} produtos com parser genérico")
    else:
        if "GUIA" in doc_type:
            produtos = parse_guia_generica(text)
            if produtos:
                result["produtos"] = produtos
                print(f"✅ Extraídos {len(produtos)} produtos com parser genérico de guias")
        
        if not result.get("produtos"):
            guia_products = extract_guia_remessa_products(text)
            if guia_products:
                result["produtos"] = guia_products
            else:
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

    # FALLBACK UNIVERSAL: Se nenhum parser específico extraiu produtos, usa extração universal
    if not result["produtos"] and file_path:
        print("🔄 Nenhum parser específico funcionou - tentando extração universal...")
        generic_result = parse_generic_document(text, file_path)
        
        if generic_result.get('produtos'):
            result["produtos"] = generic_result['produtos']
            print(f"✅ Extração universal bem-sucedida: {len(result['produtos'])} produtos")
            
            # Atualiza metadados se disponível
            if generic_result.get('metadata'):
                metadata = generic_result['metadata']
                if not result["supplier_name"] and metadata.get('fornecedor'):
                    result["supplier_name"] = metadata['fornecedor']
                if not result["document_number"] and metadata.get('documento'):
                    result["document_number"] = metadata['documento']
                if not result["delivery_date"] and metadata.get('data'):
                    result["delivery_date"] = metadata['data']
                if not result["po_number"] and metadata.get('encomenda'):
                    result["po_number"] = metadata['encomenda']

    if result["produtos"]:
        result["totals"]["total_lines"] = len(result["produtos"])
        result["totals"]["total_quantity"] = sum(p.get("quantidade", 0) for p in result["produtos"])
        
        if not result["po_number"] and result["produtos"]:
            for produto in result["produtos"]:
                ref = produto.get("referencia_ordem", "")
                po_match = re.match(r'^([A-Z0-9]+)\s+[NnºN]', ref, re.IGNORECASE)
                if po_match:
                    result["po_number"] = po_match.group(1).upper()
                    break
    elif result["lines"]:
        result["totals"]["total_lines"] = len(result["lines"])
        result["totals"]["total_quantity"] = sum(x["qty"] for x in result["lines"])

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
def create_po_from_nota_encomenda(inbound: InboundDocument, payload: dict):
    """
    Cria automaticamente PurchaseOrder + POLines a partir de uma Nota de Encomenda (Fatura).
    Extrai: número encomenda, fornecedor, produtos, quantidades, dimensões.
    """
    from .models import PurchaseOrder, POLine
    
    # Extrair número da encomenda do documento
    po_number = payload.get("document_number") or payload.get("po_number") or f"PO-{inbound.number}"
    
    # Verificar se PO já existe (evitar duplicados)
    existing_po = PurchaseOrder.objects.filter(number=po_number).first()
    if existing_po:
        print(f"⚠️ PO {po_number} já existe, vinculando documento à PO existente")
        inbound.po = existing_po
        inbound.save()
        return existing_po
    
    # Criar nova Purchase Order
    po = PurchaseOrder.objects.create(
        number=po_number,
        supplier=inbound.supplier
    )
    print(f"✅ Criada PO {po_number} para fornecedor {inbound.supplier.name}")
    
    # Extrair produtos do payload (suporta formatos: produtos ou lines)
    produtos = payload.get("produtos", [])
    if not produtos:
        produtos = payload.get("lines", [])
    
    # Criar POLines para cada produto
    lines_created = 0
    for produto in produtos:
        # Extrair dados do produto
        article_code = produto.get("artigo", produto.get("supplier_code", ""))
        description = produto.get("descricao", produto.get("description", ""))
        unit = produto.get("unidade", produto.get("unit", "UN"))
        qty_ordered = float(produto.get("quantidade", produto.get("qty", 0)))
        
        if not article_code or qty_ordered <= 0:
            continue
        
        # Usar article_code como internal_sku (pode ser mapeado depois)
        POLine.objects.create(
            po=po,
            internal_sku=article_code,
            description=description,
            unit=unit,
            qty_ordered=qty_ordered,
            tolerance=0
        )
        lines_created += 1
    
    print(f"✅ Criadas {lines_created} linhas na PO {po_number}")
    
    # Vincular documento à PO criada
    inbound.po = po
    inbound.save()
    
    return po


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

    # Se for Nota de Encomenda (FT), criar PurchaseOrder e retornar
    if inbound.doc_type == 'FT':
        print(f"📋 Processando Nota de Encomenda: {inbound.number}")
        po = create_po_from_nota_encomenda(inbound, payload)
        
        # Criar MatchResult básico para Nota de Encomenda
        res, _ = MatchResult.objects.get_or_create(inbound=inbound)
        produtos = payload.get("produtos", payload.get("lines", []))
        res.status = "matched"
        res.summary = {
            "lines_ok": len(produtos),
            "lines_issues": 0,
            "total_lines_in_document": len(produtos),
            "lines_read_successfully": len(produtos),
            "po_created": po.number if po else None
        }
        res.certified_id = hashlib.sha256(
            (str(inbound.id) + str(payload)).encode()).hexdigest()[:16]
        res.save()
        
        print(f"✅ Nota de Encomenda processada: PO {po.number if po else 'N/A'} criada")
        return res

    # Validar se ficheiro é ilegível (apenas para Guias de Remessa)
    texto_extraido = payload.get("texto_completo", "")
    produtos_extraidos = payload.get("produtos", [])
    linhas_extraidas = payload.get("lines", [])
    
    # Considerar ficheiro ilegível se:
    # - Texto muito curto (<100 chars)
    # - Documento é guia/fatura mas 0 produtos extraídos
    doc_type = payload.get("tipo_documento", "")
    is_document_with_products = any(x in doc_type for x in ["FATURA", "GUIA"])
    
    if len(texto_extraido) < 100:
        ExceptionTask.objects.create(
            inbound=inbound,
            line_ref="OCR",
            issue="Ficheiro ilegível - texto extraído muito curto (menos de 100 caracteres)"
        )
    elif is_document_with_products and not produtos_extraidos and not linhas_extraidas:
        ExceptionTask.objects.create(
            inbound=inbound,
            line_ref="OCR",
            issue="Ficheiro ilegível - nenhum produto foi extraído do documento"
        )
    
    # Se texto pdfplumber era curto E nenhum produto foi extraído → ficheiro ilegível
    if payload.get("baixa_qualidade_texto") and not produtos_extraidos and not linhas_extraidas:
        ExceptionTask.objects.create(
            inbound=inbound,
            line_ref="OCR",
            issue="Ficheiro ilegível - qualidade de imagem muito baixa (texto quase vazio mesmo após OCR)"
        )
    
    # Validar qualidade dos produtos extraídos
    if produtos_extraidos:
        # Verificar se produtos têm dados válidos
        produtos_invalidos = 0
        for produto in produtos_extraidos:
            codigo = produto.get('artigo', '')
            quantidade = produto.get('quantidade', 0)
            
            # Produto inválido se:
            # - Código muito curto (<5 chars) ou vazio
            # - Quantidade = 0 ou inválida
            if len(codigo) < 5 or quantidade <= 0:
                produtos_invalidos += 1
        
        # Se >50% dos produtos são inválidos, ficheiro está desformatado
        taxa_invalidos = produtos_invalidos / len(produtos_extraidos)
        if taxa_invalidos > 0.5:
            ExceptionTask.objects.create(
                inbound=inbound,
                line_ref="OCR",
                issue=f"Ficheiro desformatado - {produtos_invalidos}/{len(produtos_extraidos)} produtos com dados inválidos (códigos curtos ou quantidades zero)"
            )

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
                    dims = produto.get("dimensoes", "")
                    # dimensoes pode ser string (Tesseract) ou dicionário (formato antigo)
                    if isinstance(dims, str):
                        dimensoes = dims
                    elif isinstance(dims, dict) and any(dims.values()):
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
                    dims = payload_line.get("dimensoes", "")
                    # dimensoes pode ser string (Tesseract) ou dicionário (formato antigo)
                    if isinstance(dims, str):
                        dimensoes = dims
                    elif isinstance(dims, dict) and any(dims.values()):
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
