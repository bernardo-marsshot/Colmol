
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

---

# 🚀 Ollama Proxy Server (Novo)

Proxy HTTP Express para Ollama com streaming completo, timeouts altos (>60s), e seleção automática de modelos.

## Características

- ✅ **Streaming completo** sem buffer (SSE/chunked)
- ✅ **Timeouts altos**: keepAlive=610s, headers=620s (resolve timeout de 60s)
- ✅ **Seleção automática**: cheap_text (texto) vs vision (imagens)
- ✅ **Upload de imagens** via multipart/form-data
- ✅ **CPU-only otimizado**: OLLAMA_NUM_PARALLEL=1, mmap ativado
- ✅ **CORS configurado** para localhost e Replit

## Endpoints

### `GET /health`
Verifica status do Ollama.

```bash
curl http://localhost:3000/health
# Response: {"status":"ok","ollama":"ready","models":1}
```

### `POST /generate`

**Texto simples (modelo cheap_text):**
```bash
curl -N http://localhost:3000/generate \
  -H "content-type: application/json" \
  -d '{"prompt":"Diz olá em 10 palavras.","stream":true}'
```

**Com imagem (modelo vision):**
```bash
curl -N http://localhost:3000/generate \
  -F "prompt=Descreve esta imagem." \
  -F "image=@exemplo.jpg"
```

## Configuração (models.json)

```json
{
  "cheap_text": {
    "model": "llava:latest",
    "options": { "num_ctx": 1024, "batch_size": 256 }
  },
  "vision": {
    "model": "llava:latest",
    "options": { "num_ctx": 2048, "batch_size": 256 }
  }
}
```

## Iniciar Sistema Completo

```bash
bash start.sh
```

Isso inicia:
1. Ollama Server (porta 8000) - CPU-only, parallel=1
2. Node.js Proxy (porta 3000) - timeouts altos
3. Django App (porta 5000) - aplicação principal

## Otimização de Custos (CPU)

- Modelos quantizados (Q4_0, Q3_K_M)
- `num_ctx` baixo (1024-2048)
- `OLLAMA_NUM_PARALLEL=1`
- mmap ativado (sem `--no-mmap`)
- Modelo cheap_text para texto, vision só quando necessário
