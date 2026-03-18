# Spec v3: Frappe CRM + DocuSeal + Holded + Stripe

**Версия:** 3.0
**Дата:** 2026-03-18
**Статус:** Ready for implementation
**Изменения vs v2.2:** Провайдер подписи заменён с DocuSign на DocuSeal (Cloud EU). Приложение переименовано в `frappe_docuseal`. Кастомные поля переименованы в `esign_*`. Auth упрощён с JWT Grant до API key. Бизнес-логика без изменений.

---

## Контекст

Когда пользователь регистрируется на сайте (Next.js) через email или Google — в Frappe CRM автоматически создаётся лид в статусе `New`. Если лид с таким email уже существует — дубль не создаётся, возвращается ID существующего.

Frappe CRM разделяет Lead (потенциальный клиент) и Deal (конкретная сделка). Lead отвечает за захват и квалификацию. После квалификации Lead конвертируется в Deal через встроенную кнопку «Convert to Deal» (при этом создаются Contact + Organization). Весь коммерческий pipeline живёт на Deal.

**Стек:**
- Backend CRM: Frappe (self-hosted), приложение `frappe_docuseal`
- Frontend/сайт: Next.js (App Router)
- Auth на сайте: NextAuth.js или Supabase Auth
- Юридический слой: **DocuSeal** (contracts + GDPR consent), Cloud EU (`api.docuseal.eu`)
- Коммерческий слой: Holded (invoicing) + Stripe (payments)
- Налоговый слой: внешняя gestoría (работает из своего софта, получает данные из Holded)

---

## Миграция со старого приложения (frappe_docusign)

> Выполнить **один раз**, перед установкой нового приложения.

```bash
# 1. Удалить старое приложение из сайта
bench --site {site} uninstall-app frappe_docusign --yes

# 2. Удалить код из bench
bench remove-app frappe_docusign

# 3. Удалить оставшиеся кастомные поля docusign_* (если остались)
bench --site {site} console
```
```python
for f in frappe.get_all("Custom Field", filters={"dt": "CRM Deal", "fieldname": ["like", "docusign_%"]}, pluck="name"):
    frappe.delete_doc("Custom Field", f)
frappe.db.commit()
exit()
```
```bash
# 4. Удалить старый CRM Form Script (если остался)
bench --site {site} console
```
```python
if frappe.db.exists("CRM Form Script", "DocuSign Buttons - CRM Deal"):
    frappe.delete_doc("CRM Form Script", "DocuSign Buttons - CRM Deal")
    frappe.db.commit()
exit()
```
```bash
# 5. Удалить DocuSign Settings DocType данные (если остались)
bench --site {site} console
```
```python
if frappe.db.exists("DocType", "DocuSign Settings"):
    frappe.delete_doc("DocType", "DocuSign Settings", force=True)
    frappe.db.commit()
exit()
```

После этого — установка нового приложения (см. секцию «Установка»).

---

## Что нужно реализовать

### Lead (захват + квалификация) — без изменений
1. **Frappe:** файл `frappe_docuseal/api/crm_lead.py` — whitelisted endpoint (копия из v2.2)
2. **Frappe:** тесты `frappe_docuseal/api/tests/test_crm_lead.py` (копия из v2.2)
3. **Next.js:** утилита `lib/crm.ts` — server-side вызов Frappe API (без изменений vs v2.2)
4. **Next.js:** вызов из auth callback при регистрации нового пользователя
5. **Next.js:** middleware для сбора UTM-параметров в cookie
6. **Frappe:** создать служебного пользователя + API Key
7. **Frappe:** Lead Statuses — дефолтные (без изменений)

### Deal (коммерческий pipeline) — провайдер подписи заменён
8. **Frappe:** Deal Statuses — кастомные (без изменений vs v2.2)
9. **Frappe:** кастомные поля на CRM Deal: `service_type`, `preferred_language`, `esign_*`
10. **Frappe:** автоматическая отправка DocuSeal submission при переходе Deal в `Contract Sent`
11. **Frappe:** webhook endpoint для получения статуса подписания из DocuSeal

---

## Часть 1: Frappe — Конфигурация

### 1.1 Lead Statuses — без изменений

Дефолтные Lead Statuses Frappe CRM (New, Contacted, Nurture, Qualified, Unqualified, Junk) подходят без изменений. Подробности — см. spec v2.2 секция 1.4.

### 1.2 Deal Statuses — без изменений

| # | Status | Type | Color | Описание |
|---|--------|------|-------|----------|
| 1 | New | Open | gray | Deal создан из Lead. Ops заполняет service_type и preferred_language |
| 2 | Contract Sent | Ongoing | orange | Документы отправлены на подпись через DocuSeal |
| 3 | Contract Signed | Ongoing | blue | Клиент подписал. Можно выставлять счёт |
| 4 | Invoice Sent | Ongoing | yellow | Счёт в Holded, Stripe payment link отправлен |
| 5 | In Progress | Ongoing | purple | Оплата получена, услуга оказывается |
| 6 | Won | Won | green | Услуга оказана, кейс закрыт |
| 7 | Lost | Lost | red | Отказ, неоплата, отмена |

**Создание:** автоматически при `bench install-app` (install.py).
**Удаление дефолтных:** вручную в Desk → CRM Deal Status → удалить: Qualification, Demo/Making, Proposal/Quotation, Negotiation, Ready to Close.

### 1.3 Переходы Deal

| Переход | Кто | Триггер |
|---------|-----|---------|
| `New` → `Contract Sent` | Ops (вручную) | Frappe автоматически отправляет DocuSeal submission |
| `Contract Sent` → `Contract Signed` | **Автоматически** | DocuSeal webhook `submission.completed` |
| `Contract Signed` → `Invoice Sent` | Ops (вручную) | Ops создаёт invoice в Holded |
| `Invoice Sent` → `In Progress` | Ops (вручную) | Оплата подтверждена |
| `In Progress` → `Won` | Ops (вручную) | Услуга оказана |
| Любой → `Lost` | Sales/Ops | Отказ на любом этапе |

---

## Часть 2: DocuSeal Settings — DocType

### 2.1 Тип: Single Document (глобальный синглтон)

**Модуль:** `Docuseal`
**Права:** System Manager (read + write)

### 2.2 Поля

| Поле | Тип | Описание |
|------|-----|----------|
| `enabled` | Check | Мастер-переключатель интеграции |
| `api_url` | Data | URL API. По умолчанию: `https://api.docuseal.eu`. Для self-hosted — свой URL |
| `api_key` | Password | API ключ из DocuSeal → Console → API. Доступ через `get_password("api_key")` |
| `default_template_id` | Data | ID шаблона DocuSeal по умолчанию. В будущем — маппинг service_type → template_id |
| `webhook_url` | Data (read_only) | Автозаполняется: `https://{site}/api/method/frappe_docuseal.api.webhook.handle_docuseal_event`. Для копирования в DocuSeal |

### 2.3 Валидация (docuseal_settings.py)

```python
class DocuSealSettings(Document):
    def validate(self):
        if self.enabled:
            self._validate_required_fields()
        self._set_webhook_url()

    def _validate_required_fields(self):
        for field in ("api_key", "default_template_id"):
            if not self.get(field) and not self.get_password(field, raise_exception=False):
                frappe.throw(f"{field} is required when DocuSeal is enabled.")

    def _set_webhook_url(self):
        site = frappe.utils.get_url()
        self.webhook_url = f"{site}/api/method/frappe_docuseal.api.webhook.handle_docuseal_event"
```

---

## Часть 3: Кастомные поля на CRM Deal

### 3.1 Бизнес-поля (заполняет Ops)

| Поле | Тип | Описание |
|------|-----|----------|
| `service_type` | Select | `Immigration`, `Tax Consulting`, `Sworn Translation`, `Insurance` |
| `preferred_language` | Select | `EN`, `ES` |

### 3.2 eSign-поля (read-only, заполняются автоматически)

| Поле | Тип | Описание |
|------|-----|----------|
| `esign_section` | Section Break | Коллапсируемая секция «eSign» |
| `esign_submission_id` | Data | DocuSeal submission ID (числовой) |
| `esign_status` | Select | `Pending` / `Completed` / `Declined` / `Expired` |
| `esign_sent_at` | Datetime | Когда submission создан |
| `esign_completed_at` | Datetime | Когда подписан (webhook) |
| `esign_link` | Data (URL) | Ссылка на signing form или audit log |
| `esign_error` | Small Text | Последняя ошибка |

### 3.3 Fixtures (custom_field.json)

Все поля экспортируются как fixtures с `"module": "Frappe Docuseal"`. Фильтр в hooks.py:

```python
fixtures = [
    {
        "dt": "Custom Field",
        "filters": [
            ["name", "in", [
                "CRM Deal-service_type",
                "CRM Deal-preferred_language",
                "CRM Deal-esign_section",
                "CRM Deal-esign_submission_id",
                "CRM Deal-esign_status",
                "CRM Deal-esign_sent_at",
                "CRM Deal-esign_completed_at",
                "CRM Deal-esign_link",
                "CRM Deal-esign_error",
            ]]
        ]
    }
]
```

---

## Часть 4: API — Аутентификация (auth.py)

DocuSeal использует API key в заголовке `X-Auth-Token`. Никакого JWT, RSA ключей или token cache.

```
frappe_docuseal/api/auth.py
```

### 4.1 Функции

**`get_settings()`** — возвращает DocuSeal Settings, проверяет `enabled`.

**`call_docuseal(method, path, **kwargs)`** — обёртка для HTTP-запросов:
- Собирает URL: `{api_url}{path}`
- Устанавливает заголовки: `X-Auth-Token` + `Content-Type: application/json`
- Таймаут: 30 секунд
- Возвращает `requests.Response`

### 4.2 Сравнение с DocuSign

| | DocuSign (v2) | DocuSeal (v3) |
|---|---|---|
| Auth | JWT Grant: RSA private key → JWT assertion → OAuth token | API key в заголовке |
| Token cache | Да (55 мин TTL) | Нет (ключ постоянный) |
| 401 retry | Да (invalidate + refetch) | Нет (если 401 — ключ невалидный) |
| Сложность | ~100 строк | ~20 строк |

---

## Часть 5: API — Submissions (submission.py)

Замена `envelope.py`. DocuSeal оперирует терминами **submission** (запрос на подпись) и **submitter** (подписант).

```
frappe_docuseal/api/submission.py
```

### 5.1 `send_submission(deal)`

**Whitelisted endpoint:** `POST /api/method/frappe_docuseal.api.submission.send_submission`

**Логика:**
1. Проверить: интеграция включена
2. Проверить: у Deal нет `esign_submission_id` (нет дубликатов)
3. Получить `template_id` из DocuSeal Settings (`default_template_id`)
4. Получить email и имя подписанта из Contact, привязанного к Deal
5. Вызвать DocuSeal API:

```
POST /submissions
{
    "template_id": 12345,
    "send_email": true,
    "submitters": [
        {
            "email": "client@example.com",
            "name": "Ivan Ivanov",
            "role": "Signer"
        }
    ]
}
```

6. На успех — обновить CRM Deal:
   - `esign_submission_id` ← submission ID
   - `esign_status` ← `"Pending"`
   - `esign_sent_at` ← now()
   - `esign_link` ← submitter `embed_src` (ссылка на подписание)
   - `esign_error` ← очистить
7. Вызвать `update_deal_stage(deal, "Contract Sent")`
8. `frappe.db.commit()`

**На ошибку:** записать в `esign_error`, бросить `ValidationError`.

### 5.2 `check_status(deal)`

**Whitelisted endpoint:** `GET /api/method/frappe_docuseal.api.submission.check_status`

**Логика:**
1. Получить `esign_submission_id` из Deal
2. Вызвать `GET /submissions/{id}`
3. Прочитать `status` из ответа
4. Маппинг: `pending` → `Pending`, `completed` → `Completed`, `declined` → `Declined`, `expired` → `Expired`
5. Обновить `esign_status`
6. Если `completed`:
   - `esign_completed_at` ← now()
   - `update_deal_stage(deal, "Contract Signed")`
7. `frappe.db.commit()`

### 5.3 Сравнение с DocuSign

| | DocuSign (v2) | DocuSeal (v3) |
|---|---|---|
| Терминология | Envelope → Signer | Submission → Submitter |
| Отправка | base64 PDF + anchor tag `/sig1/` | template_id + submitter email |
| Шаблоны | В коде (build payload) | В DocuSeal UI (заранее) |
| Статусы | Sent, Delivered, Completed, Declined, Voided | pending, completed, declined, expired |
| Ссылка | appdemo.docusign.com/documents/details/{id} | embed_src из ответа API |

---

## Часть 6: API — Webhook (webhook.py)

```
frappe_docuseal/api/webhook.py
```

### 6.1 Endpoint

```
POST /api/method/frappe_docuseal.api.webhook.handle_docuseal_event
```

`allow_guest=True` — DocuSeal отправляет запросы без авторизации Frappe.

### 6.2 Payload формат DocuSeal

```json
{
    "event_type": "submission.completed",
    "timestamp": "2026-03-18T12:00:00Z",
    "data": {
        "id": 123,
        "slug": "abc123",
        "status": "completed",
        "created_at": "2026-03-18T10:00:00Z",
        "completed_at": "2026-03-18T12:00:00Z",
        "submitters": [
            {
                "id": 456,
                "email": "client@example.com",
                "status": "completed",
                "documents": [
                    {"name": "Contract", "url": "https://..."}
                ]
            }
        ]
    }
}
```

### 6.3 Обработка событий

| event_type | Действие |
|------------|----------|
| `submission.completed` | `esign_status` = "Completed", `esign_completed_at` = now(), `stage` → "Contract Signed" |
| `submission.expired` | `esign_status` = "Expired" |
| `submitter.declined` | `esign_status` = "Declined", отправить email deal_owner |

### 6.4 Верификация запросов

DocuSeal Cloud **не поддерживает HMAC**. Защита:
1. Проверить что `submission_id` из payload **существует в нашей БД** как `esign_submission_id`
2. Если нет — проигнорировать (вернуть 200)
3. Идемпотентность: если статус уже `Completed` — не перезаписывать `esign_completed_at`

### 6.5 Ответ

Всегда возвращать HTTP 200 с JSON `{"status": "ok"}`. Ошибки логировать в `frappe.log_error()`.

### 6.6 Сравнение с DocuSign

| | DocuSign (v2) | DocuSeal (v3) |
|---|---|---|
| Верификация | HMAC-SHA256 (X-DocuSign-Signature-1) | Проверка submission_id в БД |
| Payload | Два формата (Legacy + SIM) | Один формат |
| Ключ ID | `envelopeId` (UUID) | `data.id` (integer) |
| Статусы | Title Case / lowercase mix | Всегда lowercase |

---

## Часть 7: API — Auto-send Hook (crm_deal_hooks.py)

```
frappe_docuseal/api/crm_deal_hooks.py
```

### 7.1 Hook: `on_deal_status_change`

Регистрация в hooks.py:
```python
doc_events = {
    "CRM Deal": {
        "validate": "frappe_docuseal.api.crm_deal_hooks.on_deal_status_change"
    }
}
```

### 7.2 Логика

```
validate fires →
  if status != "Contract Sent": return
  if doc is new (no previous): return
  if previous status was already "Contract Sent": return
  validate: service_type filled
  validate: preferred_language filled
  validate: contact email exists (from linked Contact)
  call send_submission(deal.name)
  if fails → throw ValidationError → status rolls back
```

### 7.3 Различие от v2

В v2 `_send_docusign_envelope()` был заглушкой (stub). В v3 — реальная реализация через `send_submission()`.

---

## Часть 8: CRM Form Script (JS кнопки)

```
frappe_docuseal/public/js/crm_deal_docuseal.js
```

### 8.1 Кнопки

| Кнопка | Показывать когда | Действие |
|--------|------------------|----------|
| **Send for Signing** | `status == "New"` AND нет `esign_submission_id` | Вызывает `frappe_docuseal.api.submission.send_submission` |
| **Check Status** | Есть `esign_submission_id` AND статус НЕ терминальный | Вызывает `frappe_docuseal.api.submission.check_status` |

### 8.2 Отличие от v2

- `send_envelope` с диалогом загрузки файлов → `send_submission` без диалога (шаблон уже в DocuSeal)
- Проверка `docusign_envelope_id` → `esign_submission_id`
- Терминальные: Completed, Declined, Voided → Completed, Declined, Expired

---

## Часть 9: Lead Creation API (crm_lead.py) — без изменений

Файл `frappe_docuseal/api/crm_lead.py` — **точная копия** из v2.2. Никаких изменений.

Endpoint: `POST /api/method/frappe_docuseal.api.crm_lead.create_lead`

Подробности — см. spec v2.2 секция 1.1.

---

## Часть 10: Next.js — без изменений

`lib/crm.ts` и вызов из auth callback — **без изменений** vs v2.2. Единственное отличие: endpoint path меняется с `frappe_docusign.api.crm_lead.create_lead` на `frappe_docuseal.api.crm_lead.create_lead`.

---

## Часть 11: Файловая структура

```
frappe_docuseal/
├── __init__.py                          # __version__ = "0.1.0"
├── modules.txt                          # Docuseal
├── hooks.py                             # after_install, after_migrate, doc_events, fixtures
├── install.py                           # _create_crm_deal_statuses, _upsert_crm_form_script
├── docuseal/
│   ├── __init__.py
│   └── doctype/
│       └── docuseal_settings/
│           ├── __init__.py
│           ├── docuseal_settings.json   # Single DocType
│           ├── docuseal_settings.py     # Валидация + auto webhook_url
│           └── test_docuseal_settings.py
├── api/
│   ├── __init__.py
│   ├── auth.py                          # get_settings, call_docuseal
│   ├── submission.py                    # send_submission, check_status
│   ├── webhook.py                       # handle_docuseal_event
│   ├── utils.py                         # update_deal_stage
│   ├── crm_lead.py                      # create_lead (копия из v2.2)
│   ├── crm_deal_hooks.py               # on_deal_status_change → send_submission
│   └── tests/
│       ├── __init__.py
│       ├── test_auth.py
│       ├── test_submission.py
│       ├── test_webhook.py
│       └── test_crm_lead.py
├── fixtures/
│   └── custom_field.json                # esign_* + service_type + preferred_language
└── public/
    └── js/
        └── crm_deal_docuseal.js         # Кнопки Send / Check Status
```

---

## Часть 12: Итерации

### Итерация 1: Scaffold + Settings + Auth + Fixtures

**Файлы:**
- `.gitignore`, `setup.py`, `requirements.txt`, `MANIFEST.in`, `license.txt`
- `frappe_docuseal/__init__.py`, `modules.txt`, `hooks.py`, `install.py`
- `frappe_docuseal/docuseal/doctype/docuseal_settings/` — все 4 файла
- `frappe_docuseal/api/__init__.py`, `auth.py`, `utils.py`
- `frappe_docuseal/api/tests/__init__.py`, `test_auth.py`
- `frappe_docuseal/fixtures/custom_field.json`

**Тесты Итерации 1:**
- DocuSeal Settings: singleton, валидация required fields, auto webhook_url
- Auth: get_settings throws if disabled, call_docuseal sets correct headers

**Зависимости:** `requests>=2.28` (убрать PyJWT и cryptography — не нужны для DocuSeal)

---

### Итерация 2: Submission + Webhook + Hook

**Файлы:**
- `frappe_docuseal/api/submission.py`
- `frappe_docuseal/api/webhook.py`
- `frappe_docuseal/api/crm_deal_hooks.py`
- `frappe_docuseal/api/tests/test_submission.py`
- `frappe_docuseal/api/tests/test_webhook.py`

**Тесты Итерации 2:**
- send_submission: raises if disabled, raises if submission exists, happy path sets fields, API error stores error
- check_status: raises if no submission_id, updates status, completed sets completed_at
- webhook: unknown submission_id → 200, completed updates status, idempotency, declined sends email
- crm_deal_hooks: triggers on New→Contract Sent, requires service_type/preferred_language/contact email

---

### Итерация 3: CRM Form Script + Docs + crm_lead

**Файлы:**
- `frappe_docuseal/public/js/crm_deal_docuseal.js`
- `frappe_docuseal/api/crm_lead.py`
- `frappe_docuseal/api/tests/test_crm_lead.py`
- `SETUP.md`
- `ADMIN_INSTALL_GUIDE.md`

---

## Часть 13: Установка

```bash
cd /home/frappe/frappe-bench
bench get-app https://github.com/sabitsky/artbot-frappe_docuseal
bench --site {site} install-app frappe_docuseal
bench --site {site} migrate
bench build --app frappe_docuseal
bench restart
```

---

## Часть 14: Настройка DocuSeal (после установки)

### 14.1 Создать аккаунт DocuSeal

1. Зайти на https://docuseal.eu (EU cloud)
2. Зарегистрироваться
3. Console → API → скопировать **API Key**

### 14.2 Создать шаблон в DocuSeal

1. DocuSeal UI → Templates → New Template
2. Загрузить PDF договора
3. Разместить поля: signature, date, name, email
4. Сохранить
5. Скопировать **Template ID** из URL или списка

### 14.3 Заполнить DocuSeal Settings в Frappe

Открыть: `https://{site}/app/docuseal-settings`

| Поле | Значение |
|------|----------|
| Enabled | ✓ |
| API URL | `https://api.docuseal.eu` (по умолчанию) |
| API Key | Из DocuSeal Console → API |
| Default Template ID | ID шаблона из DocuSeal |

### 14.4 Настроить Webhook в DocuSeal

1. DocuSeal → Settings → Webhooks → Add
2. URL: скопировать из поля `webhook_url` в DocuSeal Settings Frappe
3. Events: `submission.completed`, `submission.expired`, `submitter.declined`
4. Save

---

## Часть 15: E2E проверка

1. Создать CRM Deal в статусе `New`
2. Привязать Contact с email
3. Заполнить `service_type` и `preferred_language`
4. Перевести в `Contract Sent`
5. **Ожидание:** DocuSeal отправляет email подписанту, в Deal появляется `esign_submission_id`, статус `Pending`
6. Подписант открывает email, подписывает документ
7. **Ожидание:** DocuSeal webhook → Deal переходит в `Contract Signed`, `esign_status` = "Completed"
