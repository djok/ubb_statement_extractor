# Cloudflare Email Routing - Пълно ръководство за настройка

Това ръководство описва стъпка по стъпка как да настроиш Cloudflare Email Routing + Workers за получаване на банкови извлечения.

## Предварителни изисквания

- Домейн, управляван от Cloudflare DNS
- Cloudflare акаунт (безплатен план е достатъчен)
- Работещ UBB Statement Extractor зад Cloudflare Tunnel

---

## Стъпка 1: Активирай Email Routing

### 1.1. Отвори Cloudflare Dashboard

1. Влез в https://dash.cloudflare.com
2. Избери твоя домейн
3. В лявото меню кликни **Email** → **Email Routing**

### 1.2. Активирай Email Routing

1. Кликни **Get started** или **Enable Email Routing**
2. Cloudflare ще покаже MX записите, които трябва да добавиш
3. Кликни **Add records and enable** - Cloudflare автоматично ще добави:
   - MX запис: `route1.mx.cloudflare.net` (priority 84)
   - MX запис: `route2.mx.cloudflare.net` (priority 18)
   - MX запис: `route3.mx.cloudflare.net` (priority 73)
   - TXT запис за SPF

### 1.3. Изчакай DNS пропагация

- Обикновено отнема 5-15 минути
- Можеш да провериш статуса в Email Routing страницата

---

## Стъпка 2: Създай Cloudflare Worker

### 2.1. Отвори Workers секцията

1. В Cloudflare Dashboard, кликни **Workers & Pages** в лявото меню
2. Кликни **Create application**
3. Избери **Create Worker**

### 2.2. Наименувай Worker-а

1. Въведи име: `ubb-email-forwarder`
2. Кликни **Deploy**

### 2.3. Редактирай кода

1. След deploy, кликни **Edit code**
2. Изтрий примерния код
3. Копирай целия код от `cloudflare-worker/email-forwarder.js`:

Вижте актуалния код в `cloudflare-worker/email-forwarder.js`.

4. Кликни **Save and deploy**

---

## Стъпка 3: Конфигурирай Environment Variables

### 3.1. Генерирай shared secret

В терминала изпълни:

```bash
openssl rand -hex 32
```

Запиши резултата - ще го използваш на две места.

### 3.2. Добави променливи в Worker-а

1. В Worker страницата, кликни **Settings** → **Variables**
2. Под **Environment Variables**, кликни **Add variable**

Добави следните променливи:

| Variable Name | Value | Type |
|--------------|-------|------|
| `WEBHOOK_URL` | `https://твоя-домейн.com/webhook/cloudflare` | Plain text |
| `WEBHOOK_SECRET` | (генерираният secret) | Encrypt |
| `FORWARD_TO` | (опционално) Верифициран email за препращане | Plain text |

**Относно FORWARD_TO:**
- Ако не добавиш тази променлива, email-ите ще се показват като "Dropped" в Activity Log
- Това НЕ означава, че не са обработени! Проверявай логовете на Worker-а и приложението
- За да се показват като "Forwarded", първо добави email адрес в Email Routing → Destination addresses

3. Кликни **Save and deploy**

### 3.3. Добави secret в приложението

Редактирай `.env` файла на UBB Statement Extractor:

```env
# Cloudflare webhook authentication
CLOUDFLARE_WEBHOOK_SECRET=същият-secret-като-в-worker
```

Рестартирай Docker контейнера:

```bash
docker compose restart api
```

---

## Стъпка 4: Създай Email Route

### 4.1. Отвори Email Routing

1. Върни се в **Email** → **Email Routing**
2. Кликни раздел **Routing rules**

### 4.2. Създай правило

1. Кликни **Create address**
2. Избери тип на адреса:

**Опция A: Специфичен адрес (препоръчително)**
- Custom address: `statements`
- Това създава `statements@твоя-домейн.com`

**Опция B: Catch-all (всички адреси)**
- Избери "Catch-all address"
- Внимание: ще получаваш ВСИЧКИ email-и

3. За Action, избери **Send to a Worker**
4. Избери `ubb-email-forwarder` от dropdown-а
5. Кликни **Save**

---

## Стъпка 5: Тествай настройката

### 5.1. Изпрати тестов email

Изпрати email до `statements@твоя-домейн.com` (или адреса, който си настроил).

### 5.2. Провери Worker логовете

1. Отвори **Workers & Pages** → `ubb-email-forwarder`
2. Кликни **Logs** → **Begin log stream**
3. Трябва да видиш:
   ```
   Email forwarded successfully: [Subject] from [sender]
   ```

### 5.3. Провери приложението

Провери логовете на Docker контейнера:

```bash
docker compose logs -f api
```

Трябва да видиш:
```
Received Cloudflare webhook: from=sender@example.com, subject=Test
```

---

## Стъпка 6: Настрой банката

### 6.1. Промени email адреса в банката

1. Влез в UBB Online Banking
2. Отиди в настройките за електронни извлечения
3. Промени email адреса на `statements@твоя-домейн.com`

### 6.2. Изчакай първото извлечение

Банката ще изпрати извлечение на:
- Края на месеца
- Или когато поискаш ръчно от банката

---

## Отстраняване на проблеми

### Email-ите се показват като "Dropped" в Activity Log

**Това е нормално поведение**, ако не си настроил `FORWARD_TO`.

Cloudflare показва "Dropped" когато Worker-ът обработва email-а, но не извиква `forward()`, `reply()` или `setReject()`. **Това НЕ означава, че email-ът не е обработен!**

**Как да провериш дали email-ите се обработват:**
1. Провери Worker логовете - трябва да виждаш "Email forwarded successfully"
2. Провери логовете на приложението - webhook-ът трябва да е получен
3. Провери BigQuery/GCS за импортирани данни

**Как да оправиш статуса на "Forwarded":**
1. Добави верифициран email в Cloudflare Dashboard → Email → Email Routing → Destination addresses
2. Добави `FORWARD_TO` environment variable в Worker-а с този email
3. След това email-ите ще се показват като "Forwarded" и ще получаваш копие в inbox-а си

### Email-ите не пристигат

1. **Провери MX записите:**
   ```bash
   dig MX твоя-домейн.com
   ```
   Трябва да видиш `route*.mx.cloudflare.net`

2. **Провери Email Routing статуса:**
   - Трябва да е "Active" в Dashboard-а

3. **Провери routing правилото:**
   - Дали е активно?
   - Дали сочи към правилния Worker?

### Worker грешки

1. **Провери логовете:**
   - Workers & Pages → твоя Worker → Logs

2. **Чести грешки:**
   - `WEBHOOK_URL environment variable not set` → Добави променливата
   - `Webhook failed: 401` → Провери WEBHOOK_SECRET

### Приложението не получава webhook

1. **Провери Cloudflare Tunnel:**
   ```bash
   curl https://твоя-домейн.com/health
   ```

2. **Провери endpoint-а:**
   ```bash
   curl -X POST https://твоя-домейн.com/webhook/cloudflare \
     -H "Content-Type: application/json" \
     -H "Authorization: Bearer твоя-secret" \
     -d '{"sender":"test@test.com","subject":"Test","raw_body":"test","received_at":"2024-01-01T00:00:00Z"}'
   ```

3. **Провери Docker логовете:**
   ```bash
   docker compose logs -f api
   ```

---

## Сигурност

### Препоръки

1. **Винаги използвай WEBHOOK_SECRET** - без него всеки може да изпраща фалшиви webhook-ове

2. **Cloudflare Tunnel** - осигурява допълнителна защита, скривайки реалното IP

3. **Rate limiting** - вече е включен (60 заявки/минута)

### Какво НЕ да правиш

- Не споделяй WEBHOOK_SECRET публично
- Не използвай HTTP (само HTTPS)
- Не деактивирай rate limiting-а

---

## Цени

| Услуга | Безплатен план | Платен план |
|--------|----------------|-------------|
| Email Routing | Неограничено | - |
| Workers | 100,000 заявки/ден | $5/мес за 10M заявки |
| Cloudflare Tunnel | Безплатно | - |

За нормална употреба (няколко извлечения на месец), безплатният план е напълно достатъчен.

---

## Полезни команди

```bash
# Провери MX записи
dig MX твоя-домейн.com

# Тествай webhook endpoint
curl -X POST https://твоя-домейн.com/webhook/cloudflare \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $CLOUDFLARE_WEBHOOK_SECRET" \
  -d '{"sender":"test@example.com","subject":"Test","raw_body":"From: test@example.com\nSubject: Test\n\nTest body","received_at":"2024-01-01T00:00:00Z"}'

# Провери логове
docker compose logs -f api

# Рестартирай след промяна на .env
docker compose restart api
```

---

## Следващи стъпки

След успешна настройка:

1. Изчакай първото банково извлечение
2. Провери че транзакциите се импортират в BigQuery
3. Използвай monitoring dashboard-а за преглед
