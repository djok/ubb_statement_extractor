# Политика за сигурност

## Докладване на уязвимости

Ако откриете уязвимост в сигурността, моля **НЕ** отваряйте публичен Issue.

Вместо това, изпратете email до: [security@example.com]

Моля включете:
- Описание на уязвимостта
- Стъпки за възпроизвеждане
- Потенциално въздействие
- Предложено решение (ако имате)

Ще отговорим в рамките на 48 часа.

## Поддържани версии

| Версия | Поддържана |
|--------|------------|
| latest | Да         |

## Мерки за сигурност

Този проект включва следните защитни механизми:

### Защита на входни данни

- **ZIP bomb защита**: Ограничение на compression ratio (100:1) и максимален размер (50MB)
- **Path traversal защита**: Валидация на файлови пътища
- **Null byte injection защита**: Филтриране на null bytes
- **File size limits**: Максимален размер на ZIP файл (10MB)

### API сигурност

- **Rate limiting**: 60 заявки на минута
- **HMAC signature validation**: За webhook endpoints
- **Security headers**: Content-Security-Policy, X-Frame-Options, и др.
- **Input validation**: Pydantic модели за всички входни данни

### Аутентикация

- **OAuth2/OIDC**: Zitadel интеграция за production
- **API Key**: За admin endpoints (развойна среда)
- **Session management**: Secure cookies

### Audit

- **Audit logging**: Логване на всички операции с IP адрес
- **Import tracking**: История на всички импорти в BigQuery

## Най-добри практики при deployment

1. **Никога не commit-вайте secrets** - използвайте environment variables
2. **Използвайте HTTPS** - винаги, включително за вътрешни услуги
3. **Ротирайте credentials** - редовно сменяйте API ключове и пароли
4. **Ограничете достъпа** - принципът на най-малките привилегии
5. **Мониторинг** - следете audit логовете за необичайна активност

## Сигурност на данните

- Банковите извлечения съдържат чувствителна финансова информация
- Използвайте encryption at rest за GCS bucket
- Ограничете достъпа до BigQuery dataset
- Редовно преглеждайте IAM permissions

## Известни ограничения

- PDF паролата се съхранява като environment variable (необходимо за decrypt)
- Local storage на JSON файлове не е криптирано
- Audit логовете съдържат IP адреси (GDPR съображения)

## Актуализации

Следете за security updates:
- Python dependencies: `pip list --outdated`
- Docker images: `docker pull` редовно
- GCP services: следете Cloud Security бюлетините
