# UBB Statement Extractor

Автоматизирана система за извличане на данни от банкови извлечения на Обединена българска банка (ОББ/UBB) и съхраняването им в Google BigQuery.

## Възможности

- **Автоматично получаване** на банкови извлечения чрез email webhook (Postal или Cloudflare Email Routing)
- **Извличане на данни** от криптирани PDF файлове в ZIP архиви
- **Парсване на транзакции** от българскоезични извлечения
- **Съхранение в BigQuery** за анализ и отчети
- **Архивиране в GCS** на оригинални документи
- **Мониторинг dashboard** с визуализации и известия за пропуснати извлечения
- **Enterprise security** - rate limiting, audit logging, OAuth2/OIDC

## Архитектура

```
                              ┌─────────────────┐
Email (Postal)        ───────►│                 │
                              │  Webhook API    │──► PDF Extractor ──► BigQuery + GCS
Email (Cloudflare)    ───────►│                 │          │
                              └─────────────────┘          ▼
                                                   Streamlit Dashboard
```

### Email приемане - два варианта

| Метод | Описание | Изисквания |
|-------|----------|------------|
| **Cloudflare Email Routing** | Препоръчително. Cloudflare получава email-ите и ги препраща чрез Worker към webhook. | Домейн в Cloudflare (безплатен план) |
| **Postal** | Self-hosted mail сървър. | VPS с публично IP и порт 25 |

## Бърз старт

### Предварителни изисквания

- Docker и Docker Compose
- Google Cloud Platform акаунт с:
  - BigQuery dataset
  - Cloud Storage bucket
  - Service Account с необходимите права

### 1. Клониране на репозиторито

```bash
git clone https://github.com/your-username/ubb-statement-extractor.git
cd ubb-statement-extractor
```

### 2. Конфигурация

```bash
# Копирайте примерните конфигурационни файлове
cp .env.example .env
cp .streamlit/secrets.toml.example .streamlit/secrets.toml

# Създайте директория за GCP credentials
mkdir -p secrets
# Копирайте вашия service account JSON файл
cp /path/to/your-service-account.json secrets/gcp-credentials.json
```

Редактирайте `.env` файла:

```bash
# Задължителни настройки
PDF_PASSWORD=вашата-парола-за-zip     # Паролата от UBB за ZIP файловете
GCS_BUCKET=your-bucket-name            # Име на GCS bucket
GOOGLE_APPLICATION_CREDENTIALS=/app/secrets/gcp-credentials.json
```

### 3. Стартиране с Docker Compose

```bash
# Стартиране на всички услуги
docker-compose up -d

# Проверка на логовете
docker-compose logs -f
```

### 4. Достъп до услугите

- **API**: http://localhost:8000
- **Monitoring Dashboard**: http://localhost:8501

## Ръчна обработка (CLI)

За обработка на единично извлечение:

```bash
# С Docker
docker-compose run --rm extractor python -m src.main /app/source/statement.zip

# Локално (изисква Python 3.11+)
pip install -r requirements.txt
PDF_PASSWORD=парола python -m src.main path/to/statement.zip
```

## Структура на проекта

```
├── src/
│   ├── main.py              # CLI entry point
│   ├── extractor.py         # PDF parser
│   ├── models.py            # Data models
│   ├── api/                 # FastAPI webhook handler
│   ├── monitoring/          # Streamlit dashboard
│   ├── services/
│   │   ├── bigquery/        # BigQuery integration
│   │   └── storage/         # GCS integration
│   └── security/            # Security utilities
├── cloudflare-worker/       # Cloudflare Email Worker
│   ├── email-forwarder.js   # Worker код
│   ├── wrangler.toml        # Wrangler конфигурация
│   └── README.md            # Worker документация
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
└── docs/                    # Documentation
```

## API Endpoints

| Endpoint | Метод | Описание |
|----------|-------|----------|
| `/` | GET | API информация |
| `/health` | GET | Health check |
| `/webhook/postal` | POST | Получаване на emails от Postal |
| `/webhook/cloudflare` | POST | Получаване на emails от Cloudflare Worker |
| `/admin/reprocess` | POST | Преобработка на ZIP файлове |
| `/admin/import-log` | GET | История на импортите |

## Мониторинг Dashboard

Streamlit dashboard-ът предоставя:

- **Overview** - ключови метрики и графики
- **Gap Detection** - откриване на пропуснати извлечения
- **Import Log** - история на обработките
- **Validation Issues** - проблеми с балансите
- **Transactions** - списък и анализ на транзакции
- **Analytics** - обобщени статистики

## Типове транзакции

Системата разпознава следните типове:

- `SEPA_INCOMING` - Входящи SEPA преводи
- `SEPA_OUTGOING` - Изходящи SEPA преводи
- `CARD_TRANSACTION` - Картови плащания
- `FEE` - Такси
- `TRANSFER_FEE` - Такси за преводи
- `INTERNAL_TRANSFER` - Вътрешни преводи
- `CURRENCY_EXCHANGE` - Валутни операции

## Сигурност

- ZIP bomb защита (лимит на компресия 100:1)
- Path traversal превенция
- Rate limiting (60 req/min)
- HMAC signature валидация за webhooks
- Security headers middleware
- Audit logging
- Zitadel OAuth2/OIDC поддръжка

## Deployment

Вижте [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) за подробно ръководство за deployment.

### Cloudflare Email Routing (препоръчително)

За настройка на Cloudflare Email Routing + Workers:

1. Вижте [docs/CLOUDFLARE_EMAIL_SETUP.md](docs/CLOUDFLARE_EMAIL_SETUP.md) за пълно ръководство
2. Cloudflare Worker кодът е в [cloudflare-worker/](cloudflare-worker/)

**Предимства на Cloudflare:**
- Безплатен план е достатъчен
- Не изисква VPS с отворен порт 25
- Работи с Cloudflare Tunnel
- Вградена spam защита

## Принос

Вижте [CONTRIBUTING.md](CONTRIBUTING.md) за насоки как да допринесете към проекта.

## Лиценз

Този проект е лицензиран под MIT License - вижте [LICENSE](LICENSE) файла за детайли.

## Поддръжка

При проблеми или въпроси, моля отворете Issue в GitHub репозиторито.

---

**Внимание**: Този проект е предназначен за лична употреба за обработка на собствени банкови извлечения. Уверете се, че спазвате всички приложими закони и условия за ползване на банкови услуги.
