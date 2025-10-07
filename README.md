
# COLMOL — Protótipo Django (Receção Inteligente)

Protótipo simples para **matching** entre **Nota de Encomenda (PO)** e **Guia de Remessa/Fatura** com:
- Upload de PDFs/Imagens (stub de OCR)
- Extração e normalização (simulada)
- Mapeamento **código fornecedor ↔ SKU interno**
- Validação de quantidades (com tolerância)
- **Certificação digital** (hash) por receção
- **Gestão por exceções**
- **Dashboard** com KPIs e lista de documentos
- Admin Django para manutenção de catálogos e regras

> ⚠️ Este protótipo usa um **OCR falso (stub)** para demonstração. Em produção, ligar a AWS Textract / Google Document AI / Azure Form Recognizer.

## Como correr
```bash
python -m venv .venv && source .venv/bin/activate  # (Windows: .venv\Scripts\activate)
pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser
python manage.py load_demo   # cria fornecedor, PO, linhas e mappings
python manage.py runserver
```

## Como testar rapidamente
1. Entre em **/admin** e confirme os dados de demonstração.
2. Vá a **/upload** e carregue um PDF/Imagem qualquer (o OCR é simulado e preenche duas linhas).
3. Veja o **matching** na página do documento, incluindo exceções e certificação.
4. Explore o **Dashboard** inicial em `/`.

## Próximos passos
- Trocar o `fake_ocr_extract` por integração real (Textract/Document AI).
- Conector de email IMAP para ingestão automática.
- PWA móvel para doca/QR e conferência física.
- Export para PHC (CSV/Excel ou API/ODBC).
- KPIs por fornecedor e ranking de qualidade documental.
