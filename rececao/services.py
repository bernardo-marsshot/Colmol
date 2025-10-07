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

    result = parse_portuguese_document(text_content, qr_codes, texto_pdfplumber_curto)
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
    import time
    try:
        print("📄 Converter PDF → imagens (OCR)…")
        
        # Converter PDF → imagens primeiro
        start_time = time.time()
        pages = convert_from_path(file_path, dpi=200)  # Reduzir DPI para 200 (mais rápido)
        conversion_time = time.time() - start_time
        
        # Se conversão demorou muito (>20s), ficheiro pode ter problemas
        if conversion_time > 20:
            print(f"⚠️ Conversão PDF demorou {conversion_time:.1f}s - possível ficheiro problemático")
        
        all_text = ""
        all_qr_codes = []
        
        for i, page in enumerate(pages, 1):
            print(f"🔍 Página {i}/{len(pages)}")
            
            # Limite de tempo por página: 15 segundos
            page_start = time.time()
            
            qr_codes = detect_and_read_qrcodes(page, page_number=i)
            all_qr_codes.extend(qr_codes)
            
            # OCR da página
            try:
                page_text = pytesseract.image_to_string(
                    page, config="--psm 6 --oem 3 -l por", lang="por", timeout=15)
                if page_text.strip():
                    all_text += f"\n--- Página {i} ---\n{page_text}\n"
            except RuntimeError as e:
                if "timeout" in str(e).lower():
                    print(f"⚠️ Timeout OCR na página {i} - imagem de má qualidade")
                    # Não adiciona texto desta página
                else:
                    raise
            
            page_time = time.time() - page_start
            if page_time > 10:
                print(f"⚠️ Página {i} demorou {page_time:.1f}s - qualidade baixa")
        
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


def detect_document_type(text: str):
    """Detecta automaticamente o tipo de documento português."""
    text_lower = text.lower()
    
    if "elastron" in text_lower and "fatura" in text_lower:
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


def parse_portuguese_document(text: str, qr_codes=None, texto_pdfplumber_curto=False):
    """Extrai cabeçalho (req/doc/fornecedor/data) e linhas de produto."""
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

    if doc_type == "FATURA_ELASTRON":
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
def process_inbound(inbound: InboundDocument):
    payload = real_ocr_extract(inbound.file.path)

    if payload.get("error"):
        ExceptionTask.objects.create(
            inbound=inbound,
            line_ref="OCR",
            issue=f"OCR extraction failed: {payload['error']}")

    inbound.parsed_payload = payload
    inbound.save()

    # Validar se ficheiro é ilegível
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
