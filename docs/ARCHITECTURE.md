# Архитектура

## Общ преглед

UBB Statement Extractor е система за автоматизирана обработка на банкови извлечения, състояща се от няколко компонента.

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           Email Flow                                     │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│   UBB Bank ──▶ Email ──▶ Postal Server ──▶ Webhook ──▶ FastAPI          │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
                                                           │
                                                           ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                        Processing Pipeline                               │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│   ZIP Extract ──▶ PDF Decrypt ──▶ Text Extract ──▶ Parse ──▶ Validate   │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
                                                           │
                                                           ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                          Storage Layer                                   │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│   ┌──────────────┐    ┌──────────────┐    ┌──────────────┐              │
│   │   BigQuery   │    │     GCS      │    │  Local JSON  │              │
│   │  (Analytics) │    │  (Archive)   │    │   (Backup)   │              │
│   └──────────────┘    └──────────────┘    └──────────────┘              │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
                                                           │
                                                           ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                        Monitoring Layer                                  │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│   Streamlit Dashboard ◀── BigQuery Queries ◀── Statement/Transaction    │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

## Компоненти

### 1. API Layer (`src/api/`)

**FastAPI приложение** за получаване на webhooks.

```
src/api/
├── app.py          # FastAPI application, routes, middleware
└── schemas.py      # Pydantic request/response models
```

**Endpoints:**
- `POST /webhook/postal` - Получаване на emails от Postal
- `POST /admin/reprocess` - Преобработка на файлове
- `GET /admin/import-log` - История на импорти
- `GET /health` - Health check

**Security:**
- Rate limiting (60/min)
- HMAC signature validation (optional)
- Admin API key authentication
- Security headers middleware

### 2. PDF Extractor (`src/extractor.py`)

**Извличане на данни от PDF** файлове с regex patterns.

**Процес:**
1. Разархивиране на ZIP с парола (AES-256)
2. Извличане на текст от PDF (pdfplumber)
3. Парсване на header информация
4. Извличане на транзакции
5. Валидация на баланси

**Regex Patterns:**
- Account holder, IBAN
- Period dates
- Opening/closing balances
- Individual transactions
- Counterparty information

### 3. Data Models (`src/models.py`)

**Pydantic модели** за типизация и валидация.

```python
# Основни модели
TransactionType    # Enum: SEPA_INCOMING, CARD_TRANSACTION, etc.
Balance            # EUR + BGN amounts
Transaction        # Single transaction record
BankStatement      # Complete statement with transactions
```

**Функционалност:**
- Automatic validation
- JSON serialization
- Balance verification
- Type inference

### 4. Services Layer (`src/services/`)

#### BigQuery Integration (`src/services/bigquery/`)

```
bigquery/
├── client.py       # BigQuery client wrapper
├── importer.py     # Statement/transaction import logic
├── schema.py       # Table schema definitions
├── idempotency.py  # Deduplication via checksums
└── exceptions.py   # Custom exceptions
```

**Таблици:**
- `statements` - Извлечения (partitioned by date)
- `transactions` - Транзакции (clustered by IBAN)
- `import_log` - История на импорти

**Features:**
- Automatic table creation
- Upsert logic
- Checksum-based deduplication
- Streaming inserts

#### Storage Integration (`src/services/storage/`)

```
storage/
├── client.py       # GCS client wrapper
└── uploader.py     # Upload logic with path structure
```

**Path Structure:**
```
gs://bucket/
└── {IBAN}/
    └── {YYYY}/
        └── {MM}/
            └── {DD}/
                ├── statement.pdf
                ├── statement.json
                └── original.zip
```

### 5. Security Layer (`src/security/`)

```
security/
├── file_validation.py  # ZIP bomb, path traversal protection
├── audit.py            # Audit logging
├── headers.py          # Security headers middleware
└── zitadel.py          # Zitadel auth helpers
```

**Защити:**
- Compression ratio limit (100:1)
- Maximum uncompressed size (50MB)
- Path traversal prevention
- Filename sanitization
- IP audit logging

### 6. Monitoring Dashboard (`src/monitoring/`)

```
monitoring/
├── app.py              # Main Streamlit app
├── auth.py             # Basic authentication
├── queries.py          # BigQuery queries
├── gap_detector.py     # Missing statement detection
└── zitadel_auth.py     # OAuth2/OIDC integration
```

**Tabs:**
- Overview - Key metrics
- Gap Detection - Missing statements
- Import Log - Processing history
- Validation Issues - Balance errors
- Transactions - Transaction list
- Analytics - Charts and summaries

### 7. CLI Tools

```
src/
├── main.py         # Single file processing
├── batch_import.py # Batch processing
├── reimport.py     # Re-import JSON to BigQuery
└── migrate_to_gcs.py # Data migration utility
```

## Data Flow

### Incoming Email Processing

```
1. Email arrives at Postal
2. Postal sends POST to /webhook/postal
3. API validates request (rate limit, signature)
4. EmailProcessor extracts ZIP attachment
5. FileValidator checks for malicious content
6. PDFExtractor processes PDF
7. Data saved to:
   - Local JSON (backup)
   - BigQuery (analytics)
   - GCS (archive)
8. Audit log updated
```

### CLI Processing

```
1. User runs: python -m src.main file.zip
2. PDFExtractor processes file
3. Output saved to output/ directory as JSON
4. Optional: Import to BigQuery with --import flag
```

## Database Schema

### statements table

| Column | Type | Description |
|--------|------|-------------|
| id | STRING | Unique ID (IBAN + date) |
| iban | STRING | Bank account IBAN |
| holder_code | STRING | Account holder code |
| holder_name | STRING | Account holder name |
| period_start | DATE | Statement period start |
| period_end | DATE | Statement period end |
| statement_date | DATE | Statement generation date |
| opening_balance_eur | NUMERIC | Opening balance EUR |
| closing_balance_eur | NUMERIC | Closing balance EUR |
| ... | ... | ... |
| source_checksum | STRING | File checksum for dedup |
| gcs_pdf_path | STRING | GCS path to PDF |
| imported_at | TIMESTAMP | Import timestamp |

### transactions table

| Column | Type | Description |
|--------|------|-------------|
| id | STRING | Unique ID |
| statement_id | STRING | FK to statements |
| posting_date | DATE | Transaction date |
| value_date | DATE | Value date |
| type | STRING | Transaction type |
| amount_eur | NUMERIC | Amount in EUR |
| amount_bgn | NUMERIC | Amount in BGN |
| is_debit | BOOLEAN | Debit flag |
| description | STRING | Transaction description |
| counterparty_name | STRING | Counterparty name |
| counterparty_iban | STRING | Counterparty IBAN |
| ... | ... | ... |

## Configuration

### Environment Variables

Вижте `.env.example` за пълен списък.

**Required:**
- `PDF_PASSWORD` - ZIP password
- `GCS_BUCKET` - Storage bucket
- `GOOGLE_APPLICATION_CREDENTIALS` - GCP credentials

**Optional:**
- `TUNNEL_TOKEN` - Cloudflare Tunnel
- `ZITADEL_*` - OAuth2 configuration
- `ADMIN_API_KEY` - Admin authentication

### Streamlit Secrets

Вижте `.streamlit/secrets.toml.example`.

## Error Handling

### Validation Errors

- Balance mismatch detection
- Turnover verification
- Transaction parsing failures

### Processing Errors

- ZIP extraction failures
- PDF parsing errors
- BigQuery import errors
- GCS upload errors

### Recovery

- All errors logged with full context
- Automatic retry for transient failures
- Manual reprocess capability via admin API

## Extensibility

### Adding New Transaction Types

1. Add enum value to `TransactionType`
2. Add detection pattern to `_infer_transaction_type()`
3. Update documentation

### Adding New Storage Backend

1. Create new module in `src/services/`
2. Implement upload interface
3. Add to processing pipeline

### Adding New Dashboard Tab

1. Add function to `src/monitoring/app.py`
2. Register in tab list
3. Create queries in `queries.py` if needed
