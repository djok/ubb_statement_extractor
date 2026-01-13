# Deployment Guide

Това ръководство описва различните начини за deployment на UBB Statement Extractor.

## Съдържание

- [Предварителни изисквания](#предварителни-изисквания)
- [Docker Compose (препоръчително)](#docker-compose-препоръчително)
- [Локална инсталация](#локална-инсталация)
- [Kubernetes](#kubernetes)
- [Production настройки](#production-настройки)

## Предварителни изисквания

### Google Cloud Platform

1. **Създайте GCP проект** (или използвайте съществуващ)

2. **Активирайте необходимите APIs**:
   ```bash
   gcloud services enable bigquery.googleapis.com
   gcloud services enable storage.googleapis.com
   ```

3. **Създайте Service Account**:
   ```bash
   gcloud iam service-accounts create ubb-extractor \
     --display-name="UBB Statement Extractor"
   ```

4. **Дайте необходимите права**:
   ```bash
   PROJECT_ID=$(gcloud config get-value project)
   SA_EMAIL="ubb-extractor@${PROJECT_ID}.iam.gserviceaccount.com"

   # BigQuery права
   gcloud projects add-iam-policy-binding $PROJECT_ID \
     --member="serviceAccount:${SA_EMAIL}" \
     --role="roles/bigquery.dataEditor"

   gcloud projects add-iam-policy-binding $PROJECT_ID \
     --member="serviceAccount:${SA_EMAIL}" \
     --role="roles/bigquery.jobUser"

   # Storage права
   gcloud projects add-iam-policy-binding $PROJECT_ID \
     --member="serviceAccount:${SA_EMAIL}" \
     --role="roles/storage.objectAdmin"
   ```

5. **Създайте ключ за Service Account**:
   ```bash
   gcloud iam service-accounts keys create gcp-credentials.json \
     --iam-account="${SA_EMAIL}"
   ```

6. **Създайте GCS bucket**:
   ```bash
   gsutil mb -l EU gs://your-bucket-name
   ```

### Postal Mail Server

За автоматично получаване на извлечения:

1. Инсталирайте и конфигурирайте [Postal](https://docs.postalserver.io/)
2. Създайте mail route към webhook endpoint-а
3. Конфигурирайте банката да изпраща извлечения на Postal адреса

## Docker Compose (препоръчително)

### Стъпка 1: Подготовка

```bash
# Клониране на репозиторито
git clone https://github.com/your-username/ubb-statement-extractor.git
cd ubb-statement-extractor

# Копиране на конфигурационни файлове
cp .env.example .env
cp .streamlit/secrets.toml.example .streamlit/secrets.toml

# Създаване на директории
mkdir -p secrets data/zip data/json data/raw
```

### Стъпка 2: Конфигурация

Редактирайте `.env`:

```bash
# Задължителни
PDF_PASSWORD=вашата-парола
GCS_BUCKET=your-bucket-name
ADMIN_API_KEY=$(openssl rand -hex 32)

# За production с публичен достъп
TUNNEL_TOKEN=your-cloudflare-tunnel-token
MONITORING_TUNNEL_TOKEN=your-monitoring-tunnel-token
```

Редактирайте `.streamlit/secrets.toml`:

```toml
[auth]
username = "admin"
password = "secure-password"
```

Копирайте GCP credentials:

```bash
cp /path/to/gcp-credentials.json secrets/gcp-credentials.json
```

### Стъпка 3: Стартиране

```bash
# Стартиране на всички услуги
docker-compose up -d

# Проверка на статуса
docker-compose ps

# Преглед на логовете
docker-compose logs -f api
docker-compose logs -f monitoring
```

### Стъпка 4: Проверка

```bash
# API health check
curl http://localhost:8000/health

# Monitoring dashboard
# Отворете http://localhost:8501 в браузър
```

## Локална инсталация

### Стъпка 1: Python среда

```bash
# Изисква Python 3.11+
python --version

# Създаване на виртуална среда
python -m venv venv
source venv/bin/activate  # Linux/Mac
# или
.\venv\Scripts\activate   # Windows

# Инсталиране на зависимости
pip install -r requirements.txt
```

### Стъпка 2: Конфигурация

```bash
cp .env.example .env
# Редактирайте .env с вашите настройки

export $(cat .env | xargs)
```

### Стъпка 3: Стартиране

**CLI за единично извлечение:**
```bash
python -m src.main path/to/statement.zip
```

**API сървър:**
```bash
uvicorn src.api.app:app --host 0.0.0.0 --port 8000
```

**Monitoring dashboard:**
```bash
streamlit run src/monitoring/app.py
```

## Kubernetes

### Пример за deployment

```yaml
# deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: ubb-extractor-api
spec:
  replicas: 2
  selector:
    matchLabels:
      app: ubb-extractor-api
  template:
    metadata:
      labels:
        app: ubb-extractor-api
    spec:
      containers:
      - name: api
        image: your-registry/ubb-extractor:latest
        ports:
        - containerPort: 8000
        envFrom:
        - secretRef:
            name: ubb-extractor-secrets
        volumeMounts:
        - name: gcp-credentials
          mountPath: /app/secrets
          readOnly: true
      volumes:
      - name: gcp-credentials
        secret:
          secretName: gcp-credentials
---
apiVersion: v1
kind: Service
metadata:
  name: ubb-extractor-api
spec:
  selector:
    app: ubb-extractor-api
  ports:
  - port: 80
    targetPort: 8000
```

### Secrets

```bash
# Създаване на secret за GCP credentials
kubectl create secret generic gcp-credentials \
  --from-file=gcp-credentials.json=secrets/gcp-credentials.json

# Създаване на secret за environment variables
kubectl create secret generic ubb-extractor-secrets \
  --from-env-file=.env
```

## Production настройки

### Сигурност

1. **HTTPS**: Винаги използвайте HTTPS
   - Cloudflare Tunnel (препоръчително)
   - nginx с Let's Encrypt
   - Cloud Load Balancer с managed SSL

2. **Аутентикация**: Конфигурирайте Zitadel OAuth2
   ```bash
   ZITADEL_ISSUER=https://your-instance.zitadel.cloud
   ZITADEL_CLIENT_ID=your-client-id
   ZITADEL_WEB_CLIENT_ID=your-web-client-id
   ```

3. **Firewall**: Ограничете достъпа до API само от Postal IP адреси

### Мониторинг

1. **Health checks**: Конфигурирайте `/health` endpoint за load balancer
2. **Logging**: Активирайте JSON logging за production
   ```bash
   LOG_JSON=true
   LOG_LEVEL=INFO
   ```
3. **Alerting**: Настройте известия за неуспешни импорти

### Backup

1. **BigQuery**: Автоматични backups от GCP
2. **GCS**: Версиониране на bucket
   ```bash
   gsutil versioning set on gs://your-bucket
   ```
3. **Database**: Експортирайте данни периодично

### Scaling

- API сървърът е stateless - може да се мащабира хоризонтално
- Използвайте Cloud Run или Kubernetes за auto-scaling
- BigQuery автоматично се мащабира

## Troubleshooting

### Проблеми с GCP credentials

```bash
# Проверка на credentials
gcloud auth activate-service-account --key-file=secrets/gcp-credentials.json
gcloud config list account
```

### Проблеми с PDF извличане

```bash
# Ръчен тест
PDF_PASSWORD=test python -c "
from src.extractor import extract_statement
result = extract_statement('test.zip')
print(result)
"
```

### Проблеми с Docker

```bash
# Rebuild на images
docker-compose build --no-cache

# Проверка на volumes
docker volume ls

# Изчистване на всичко и рестарт
docker-compose down -v
docker-compose up -d
```

### Логове

```bash
# API логове
docker-compose logs -f api

# Monitoring логове
docker-compose logs -f monitoring

# Всички логове
docker-compose logs -f
```
