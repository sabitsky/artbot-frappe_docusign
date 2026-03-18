# Frappe × DocuSign — Техническая спецификация V1 (упрощённая)

> **Проект:** ArtBot CRM  
> **Тип документа:** ТЗ для передачи разработчику  
> **Версия:** 1.3 — simplified + developer context + deployment guide  
> **Дата:** 2026-03-18

---

## 0. Что ты получишь после реализации

### Исходное состояние

Frappe CRM — чистая, стоковая установка. Нет кастомных полей, нет интеграций. Подписание документов с клиентами происходит вручную: отправляешь PDF по почте, ждёшь скан/фото, вручную сохраняешь, вручную меняешь статус сделки.

### Что изменится

**На карточке сделки появится кнопка «Отправить на подпись».** Менеджер выбирает документы, подтверждает имя и email клиента — CRM отправляет всё через DocuSign и переводит сделку в статус «Contract Sent». Никаких ручных писем.

**Клиент получает письмо от DocuSign** со ссылкой на подписание. Подписывает в браузере или с телефона. Юридически значимая электронная подпись по eIDAS.

**После подписания CRM обновляется автоматически.** DocuSign уведомляет CRM через webhook. Статус сделки сам переходит в «Contract Signed». Менеджеру ничего делать не нужно.

**Подписанные документы хранятся в DocuSign.** CRM не скачивает и не хранит PDF — на карточке сделки есть прямая ссылка на конверт в DocuSign, где можно посмотреть и скачать документы в любой момент.

**Кнопка «Проверить статус»** — для случаев, когда нужно вручную узнать, что произошло с конвертом.

### Конечный pipeline сделки

```
Lead → Qualified → Proposal Sent → [кнопка: Отправить на подпись] → Contract Sent → Contract Signed → Onboarding
```

Переход «Contract Sent → Contract Signed» происходит автоматически.

### Что НЕ входит в V1

- Хранение подписанных документов в CRM или на S3 (хранятся в DocuSign)
- Генерация документов из данных CRM (загружаются вручную)
- Подписание несколькими сторонами одновременно
- Встроенное подписание внутри интерфейса CRM
- Массовая рассылка контрактов
- Автоматический мониторинг «зависших» конвертов (есть ручная кнопка)

---

## 0.1. Технический контекст для разработчика / AI-агента

> **Это первое кастомное Frappe-приложение в проекте.** Ниже — всё, что нужно знать разработчику или AI-агенту, который будет писать код. Не пропускай этот раздел.

### Стек и языки

Frappe Framework — это full-stack веб-фреймворк. Всё приложение пишется на двух языках:

- **Python 3.10+** — серверная логика, API-эндпоинты, обработка webhook, взаимодействие с DocuSign API. Весь backend-код в `.py` файлах.
- **JavaScript (ES6, клиентский)** — кастомные кнопки на формах, диалоги, UI-логика. Client Scripts в `.js` файлах. Это не Node.js — это браузерный JS, работающий внутри Frappe UI.

Фронтенд Frappe CRM построен на **Vue.js** (Frappe UI), но для V1 нашей интеграции Vue не нужен — мы используем только Frappe Client Script API (jQuery-подобный, встроенный в фреймворк).

**Не нужны:** TypeScript, React, Next.js, Docker (если на Frappe Cloud), сборщики (Frappe сам билдит через `bench build`).

### Ключевые концепции Frappe (минимум для этой задачи)

**DocType** — модель данных. Аналог Django Model / ActiveRecord. Определяется JSON-файлом (схема полей) + Python-файлом (контроллер с бизнес-логикой). Frappe автоматически создаёт таблицу в MariaDB, REST API, форму в UI, и права доступа.

**Single DocType** — DocType, у которого только один экземпляр. Используется для настроек (как Django Settings). В нашем случае — `DocuSign Settings`.

**Whitelisted method** — Python-функция с декоратором `@frappe.whitelist()`, доступная через HTTP API (`/api/method/...`). Это основной способ создания custom API endpoints.

**Client Script** — JavaScript-код, привязанный к форме DocType. Добавляет кнопки, обработчики, валидации на UI. В нашем случае — кнопки «Отправить на подпись» и «Проверить статус» на форме CRM Deal.

**hooks.py** — конфигурация приложения. Аналог Django `settings.py` + `urls.py`. Здесь регистрируются scheduled jobs, fixtures, кастомные поля, doc events.

**Custom Field** — поле, добавленное к существующему DocType другого приложения (в нашем случае — поля `docusign_*` на CRM Deal). Определяются через `fixtures` в `hooks.py` или через UI.

**bench** — CLI-инструмент для управления Frappe-проектами. Аналог Django `manage.py` + `pip` + `npm` в одном. Основные команды: `bench new-app`, `bench --site install-app`, `bench migrate`, `bench build`, `bench start`.

### Документация — что читать

Разработчик или AI-агент **обязан** использовать следующую документацию:

| Что                        | URL                                                        | Зачем                                       |
|----------------------------|------------------------------------------------------------|----------------------------------------------|
| **Frappe Framework Docs**  | https://frappeframework.com/docs/user/en                   | Основная документация фреймворка             |
| Создание приложения        | https://frappeframework.com/docs/user/en/basics/apps       | Структура Frappe-приложения, `bench new-app` |
| DocType                    | https://frappeframework.com/docs/user/en/basics/doctypes   | Создание моделей данных                      |
| API: Whitelisted methods   | https://frappeframework.com/docs/user/en/api/rest-api      | REST API, `@frappe.whitelist()`              |
| API: Document              | https://frappeframework.com/docs/user/en/api/document      | `frappe.get_doc`, `frappe.get_single`, CRUD  |
| Client Script              | https://frappeframework.com/docs/user/en/desk/scripting/client-script | JS на формах                    |
| Hooks                      | https://frappeframework.com/docs/user/en/basics/hooks      | hooks.py, fixtures, scheduled events         |
| Custom Fields (fixtures)   | https://frappeframework.com/docs/user/en/basics/hooks#fixtures | Добавление полей к чужим DocTypes        |
| **Frappe CRM Docs**        | https://docs.frappe.io/crm                                 | Документация CRM (модели Deal, Lead, Contact)|
| **DocuSign eSign API**     | https://developers.docusign.com/docs/esign-rest-api/reference/ | REST API v2.1 — конверты, подписанты    |
| DocuSign JWT Auth          | https://developers.docusign.com/platform/auth/jwt/jwt-get-token | JWT Grant flow                        |
| DocuSign Connect Webhooks  | https://developers.docusign.com/platform/webhooks/connect/ | Настройка и обработка webhook               |

### Команды для создания приложения с нуля

```bash
# 1. Создать scaffold приложения
bench new-app frappe_docusign
# Ответить на вопросы: title, description, publisher, email, license

# 2. Установить на сайт
bench --site {site_name} install-app frappe_docusign

# 3. Включить developer mode (чтобы DocType-изменения сохранялись в JSON)
bench --site {site_name} set-config developer_mode 1

# 4. Создать DocType через UI или вручную
# UI: перейти на {site}/app/doctype/new → заполнить поля → Save
# Или создать JSON/PY файлы вручную по структуре из раздела 10

# 5. После изменений DocType — мигрировать
bench --site {site_name} migrate

# 6. После изменений JS — пересобрать
bench build --app frappe_docusign

# 7. Запустить dev-сервер
bench start

# 8. Установить Python-зависимости
cd apps/frappe_docusign
pip install -r requirements.txt
# На Frappe Cloud: зависимости из requirements.txt ставятся автоматически при деплое
```

### Особенности Frappe Cloud

Если CRM развёрнута на Frappe Cloud (frappecloud.com):

- Приложение устанавливается через UI Frappe Cloud → Apps → Install from GitHub
- `developer_mode` включается в настройках сайта на дашборде
- SSH-доступ к серверу доступен через `bench ssh`
- Деплой происходит автоматически при push в связанный git-репозиторий
- `requirements.txt` обрабатывается автоматически
- Логи доступны через дашборд → Logs

### Чего НЕ делать (типичные ошибки)

- **Не использовать Django, Flask, FastAPI** — всё строится внутри Frappe. Никаких отдельных серверов.
- **Не создавать таблицы в БД вручную** — только через DocType. Frappe управляет схемой сам.
- **Не писать SQL напрямую** (кроме отчётов) — использовать `frappe.get_doc`, `frappe.get_all`, `frappe.db.set_value`.
- **Не ставить пакеты через `npm`** для серверной логики — это Python-фреймворк.
- **Не хардкодить credentials** — хранить в DocuSign Settings (Single DocType), доставать через `frappe.get_single()`.
- **Не использовать `threading` или `asyncio`** — для фоновых задач есть `frappe.enqueue()` и `scheduler_events` в hooks.py.

---

## 1. Архитектура

```
┌─────────────┐       ┌──────────────────┐       ┌─────────────┐
│  Frappe CRM  │──────▶│  Кастомное       │──────▶│  DocuSign   │
│  (Фронтенд)  │       │  Frappe-приложение│       │  REST API   │
└─────────────┘       └──────────────────┘       └──────┬──────┘
                              ▲                         │
                              │   webhook (completed/   │
                              │   declined)             │
                              └─────────────────────────┘
```

### Компоненты

- **Кастомное Frappe-приложение** (`frappe_docusign`) — устанавливается рядом с Frappe CRM
- **DocuSign eSignature REST API v2.1** — создание конвертов
- **DocuSign Connect (Webhook)** — уведомление о подписании/отказе

---

## 2. Кастомный DocType: DocuSign Settings (Single)

Один экземпляр на сайт. Хранит credentials.

| Поле              | Тип       | Описание                                                     |
|-------------------|-----------|--------------------------------------------------------------|
| `integration_key` | Data      | OAuth Client ID из DocuSign Developer Portal                 |
| `account_id`      | Data      | DocuSign Account ID                                          |
| `base_url`        | Data      | `https://demo.docusign.net/restapi` (sandbox) / `https://na4.docusign.net/restapi` (prod) |
| `auth_server`     | Data      | `https://account-d.docusign.com` (sandbox) / `https://account.docusign.com` (prod) |
| `environment`     | Select    | `Sandbox` / `Production`                                     |
| `private_key`     | Code      | RSA-приватный ключ для JWT Grant                             |
| `user_id`         | Data      | DocuSign User ID (GUID) для имперсонации                     |
| `webhook_secret`  | Password  | HMAC-ключ для верификации webhook                            |
| `enabled`         | Check     | Главный переключатель                                        |

**Права:** только System Manager.

---

## 3. Кастомные поля на CRM Deal

Вместо отдельного DocType для логов — поля прямо на сделке. Для V1 один конверт на сделку — достаточно.

| Поле                      | Тип      | Описание                                        |
|---------------------------|----------|-------------------------------------------------|
| `docusign_envelope_id`    | Data     | DocuSign Envelope ID (GUID)                     |
| `docusign_status`         | Select   | `Sent` / `Delivered` / `Completed` / `Declined` / `Voided` |
| `docusign_sent_at`        | Datetime | Когда конверт отправлен                         |
| `docusign_completed_at`   | Datetime | Когда подписание завершено                      |
| `docusign_link`           | Data     | Прямая ссылка на конверт в DocuSign             |
| `docusign_error`          | Small Text | Последняя ошибка (если была)                  |

Все поля — в отдельной секции «DocuSign» на форме сделки, read-only для менеджера.

---

## 4. Авторизация: JWT Grant

Server-to-server, без участия пользователя после одноразового согласия.

### Одноразовая настройка

1. Создать RSA-пару в DocuSign Developer Portal
2. Сохранить приватный ключ в DocuSign Settings
3. Получить consent:
   ```
   {auth_server}/oauth/auth?response_type=code
     &scope=signature%20impersonation
     &client_id={integration_key}
     &redirect_uri={frappe_site_url}/api/method/frappe_docusign.oauth_callback
   ```

### Получение токена

```python
# frappe_docusign/api/auth.py

import jwt, time, requests, frappe

def get_access_token():
    """Возвращает access token. Кэширует на 55 минут."""
    cached = frappe.cache().get_value("docusign_access_token")
    if cached:
        return cached

    settings = frappe.get_single("DocuSign Settings")
    now = int(time.time())

    assertion = jwt.encode(
        {
            "iss": settings.integration_key,
            "sub": settings.user_id,
            "aud": settings.auth_server.replace("https://", ""),
            "iat": now,
            "exp": now + 3600,
            "scope": "signature impersonation"
        },
        settings.get_password("private_key"),
        algorithm="RS256"
    )

    resp = requests.post(
        f"{settings.auth_server}/oauth/token",
        data={
            "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
            "assertion": assertion
        }
    )
    resp.raise_for_status()
    token = resp.json()["access_token"]

    frappe.cache().set_value("docusign_access_token", token, expires_in_sec=3300)
    return token
```

---

## 5. Эндпоинт: отправка конверта

**Метод:** `frappe_docusign.api.envelope.send_envelope`

```python
@frappe.whitelist()
def send_envelope(deal, documents, signer_name, signer_email):
    """
    1. Проверить что DocuSign Settings заполнен и enabled
    2. Получить access token
    3. Для каждого файла из documents:
       - прочитать из Frappe file system
       - закодировать в base64
    4. Сформировать envelope:
       - documents[] с base64-контентом
       - recipients.signers[] с именем, email, signHereTabs (anchor /sig1/)
       - status: "sent"
    5. POST /v2.1/accounts/{account_id}/envelopes
    6. Записать в поля сделки:
       - docusign_envelope_id
       - docusign_status = "Sent"
       - docusign_sent_at = now
       - docusign_link = https://app.docusign.com/documents/details/{envelope_id}
    7. Обновить stage сделки → "Contract Sent"
    """
```

**Тело запроса к DocuSign:**

```json
{
  "emailSubject": "Please sign your documents — ArtBot",
  "documents": [
    {
      "documentBase64": "<content>",
      "name": "document_name.pdf",
      "fileExtension": "pdf",
      "documentId": "1"
    }
  ],
  "recipients": {
    "signers": [
      {
        "email": "client@example.com",
        "name": "Client Name",
        "recipientId": "1",
        "routingOrder": "1",
        "tabs": {
          "signHereTabs": [
            {
              "anchorString": "/sig1/",
              "anchorUnits": "pixels",
              "anchorXOffset": "0",
              "anchorYOffset": "0"
            }
          ]
        }
      }
    ]
  },
  "status": "sent"
}
```

**Размещение подписи:** якорный тег `/sig1/` в тексте документа. Если якорь не найден, DocuSign разместит подпись внизу последней страницы (поведение по умолчанию — приемлемо для V1).

---

## 6. Эндпоинт: webhook от DocuSign

**Метод:** `frappe_docusign.api.webhook.handle_docusign_event`  
**Флаг:** `allow_guest=True`

```python
@frappe.whitelist(allow_guest=True)
def handle_docusign_event():
    """
    1. Прочитать тело запроса и заголовок X-DocuSign-Signature-1
    2. Проверить HMAC-подпись (если не совпадает → 401, записать в Error Log)
    3. Извлечь envelope_id и status из payload
    4. Найти CRM Deal по docusign_envelope_id
    5. Если не найден → записать warning в Error Log, вернуть 200
    6. Если status == "completed":
       - docusign_status = "Completed"
       - docusign_completed_at = now
       - stage сделки → "Contract Signed"
    7. Если status == "declined":
       - docusign_status = "Declined"
       - отправить email владельцу сделки
    8. Вернуть 200 OK
    """
```

**HMAC-верификация:**

```python
import hmac, hashlib, base64

def verify_hmac(payload_bytes, signature_header, secret):
    computed = base64.b64encode(
        hmac.new(secret.encode(), payload_bytes, hashlib.sha256).digest()
    ).decode()
    return hmac.compare_digest(computed, signature_header)
```

---

## 7. Эндпоинт: ручная проверка статуса

**Метод:** `frappe_docusign.api.envelope.check_status`

```python
@frappe.whitelist()
def check_status(deal):
    """
    1. Прочитать docusign_envelope_id из сделки
    2. GET /v2.1/accounts/{account_id}/envelopes/{envelope_id}
    3. Обновить docusign_status на сделке
    4. Если completed → обновить stage и docusign_completed_at
    """
```

Вызывается кнопкой «Проверить статус» на карточке сделки.

---

## 8. Client Script: кнопки на CRM Deal

```javascript
frappe.ui.form.on('CRM Deal', {
    refresh(frm) {
        // Кнопка «Отправить на подпись» — только если stage = Proposal Sent и конверт ещё не отправлен
        if (frm.doc.stage === 'Proposal Sent' && !frm.doc.docusign_envelope_id) {
            frm.add_custom_button(__('Отправить на подпись'), () => {
                let d = new frappe.ui.Dialog({
                    title: 'Отправка документов на подпись',
                    fields: [
                        { fieldname: 'signer_name', fieldtype: 'Data', label: 'Имя клиента',
                          default: frm.doc.contact_name, reqd: 1 },
                        { fieldname: 'signer_email', fieldtype: 'Data', label: 'Email клиента',
                          default: frm.doc.contact_email, reqd: 1, options: 'Email' },
                        { fieldname: 'documents', fieldtype: 'Table', label: 'Документы',
                          fields: [
                            { fieldname: 'file', fieldtype: 'Attach', label: 'Документ', in_list_view: 1, reqd: 1 }
                          ]
                        }
                    ],
                    primary_action_label: 'Отправить через DocuSign',
                    primary_action(values) {
                        frappe.call({
                            method: 'frappe_docusign.api.envelope.send_envelope',
                            args: {
                                deal: frm.doc.name,
                                documents: values.documents.map(d => d.file),
                                signer_name: values.signer_name,
                                signer_email: values.signer_email
                            },
                            callback() {
                                frappe.msgprint(__('Документы отправлены на подпись!'));
                                frm.reload_doc();
                            }
                        });
                        d.hide();
                    }
                });
                d.show();
            }, __('DocuSign'));
        }

        // Кнопка «Проверить статус» — если конверт отправлен, но ещё не завершён
        if (frm.doc.docusign_envelope_id && !['Completed', 'Declined'].includes(frm.doc.docusign_status)) {
            frm.add_custom_button(__('Проверить статус'), () => {
                frappe.call({
                    method: 'frappe_docusign.api.envelope.check_status',
                    args: { deal: frm.doc.name },
                    callback() { frm.reload_doc(); }
                });
            }, __('DocuSign'));
        }
    }
});
```

---

## 9. Обработка ошибок (V1 — простая)

| Сценарий                             | Действие                                          |
|--------------------------------------|----------------------------------------------------|
| DocuSign API возвращает 401          | Сбросить кэш токена, получить новый, повторить раз |
| DocuSign API возвращает 400/500      | Записать текст ошибки в `docusign_error` на сделке, показать пользователю |
| HMAC-верификация webhook не проходит | Вернуть 401, записать в Error Log                  |
| Webhook пришёл, но сделка не найдена | Записать в Error Log, вернуть 200                  |

Никаких retry-очередей, exponential backoff, cron-задач. Если что-то пошло не так — менеджер видит ошибку на карточке и может нажать «Проверить статус» или написать в поддержку.

---

## 10. Структура приложения

```
frappe_docusign/
├── frappe_docusign/
│   ├── __init__.py
│   ├── hooks.py
│   ├── api/
│   │   ├── __init__.py
│   │   ├── auth.py          # JWT-токен с кэшированием
│   │   ├── envelope.py      # send_envelope, check_status
│   │   └── webhook.py       # handle_docusign_event
│   ├── docusign_settings/
│   │   ├── docusign_settings.json
│   │   └── docusign_settings.py
│   ├── fixtures/
│   │   └── custom_field.json    # Кастомные поля docusign_* для CRM Deal
│   └── public/
│       └── js/
│           └── crm_deal_custom.js
├── setup.py
└── requirements.txt              # PyJWT, cryptography, requests
```

**Что убрано по сравнению с полной версией:**
- `tasks.py` (нет scheduled jobs)
- `docusign_envelope_log/` (нет отдельного DocType для логов)
- `docusign_envelope_document/` (нет хранения файлов)

### Полный hooks.py для V1

Это центральный конфигурационный файл. Сводит все ссылки из спеки в одно место:

```python
# frappe_docusign/hooks.py

app_name = "frappe_docusign"
app_title = "Frappe DocuSign"
app_publisher = "ArtBot"
app_description = "DocuSign eSignature integration for Frappe CRM"
app_version = "0.1.0"

# Подключить Client Script к форме CRM Deal (раздел 8 спеки)
doctype_js = {
    "CRM Deal": "public/js/crm_deal_custom.js"
}

# Экспорт кастомных полей — при migrate на новом сайте поля появятся автоматически (раздел 3)
fixtures = [
    {
        "dt": "Custom Field",
        "filters": [["name", "like", "CRM Deal-docusign_%"]]
    }
]
```

---

## 11. Зависимости

| Пакет          | Версия | Назначение                 |
|----------------|--------|----------------------------|
| `PyJWT`        | ≥2.0   | Создание JWT-токенов       |
| `cryptography` | ≥3.0   | RSA-ключи для PyJWT        |
| `requests`     | ≥2.28  | HTTP-вызовы к DocuSign API |

---

## 12. Как код превращается в работающую кнопку в CRM

> Этот раздел отвечает на вопрос: «Разработчик / агент написал код — куда его деть и что нажать, чтобы в CRM появилась кнопка?»

### 12.1. Где живёт код

Код — это отдельный GitHub-репозиторий (например, `github.com/artbot-ai/frappe_docusign`). Это НЕ файлы, которые вручную копируются на сервер. Frappe устанавливает приложение из git-репозитория через CLI.

Разработчик создаёт репо со структурой из раздела 10, пушит в GitHub, и дальше — установка.

### 12.2. Как Frappe узнаёт про кастомные поля на CRM Deal

Кастомные поля (`docusign_envelope_id`, `docusign_status` и т.д.) НЕ добавляются вручную через UI. Они описываются в коде приложения и применяются автоматически при установке.

Механизм — **fixtures** в `hooks.py`:

```python
# frappe_docusign/hooks.py

fixtures = [
    {
        "dt": "Custom Field",
        "filters": [["name", "like", "CRM Deal-docusign_%"]]
    }
]
```

Разработчик один раз создаёт поля через UI (в developer mode), Frappe сохраняет их как JSON-файлы в папке `fixtures/`. При `bench --site {site} migrate` на любом другом сайте эти поля автоматически появляются на CRM Deal.

**Альтернативный способ (программный):** определить поля в `after_install` hook или через `frappe.make_custom_field()` в setup-скрипте. Оба варианта рабочие.

### 12.3. Как подключается кнопка на форме CRM Deal

Кнопки «Отправить на подпись» и «Проверить статус» добавляются через **Client Script**. Frappe загружает JS-файл автоматически, если он зарегистрирован в `hooks.py`:

```python
# frappe_docusign/hooks.py

doctype_js = {
    "CRM Deal": "public/js/crm_deal_custom.js"
}
```

Это говорит Frappe: «когда пользователь открывает форму CRM Deal — загрузи и выполни этот JS-файл». После `bench build --app frappe_docusign` скрипт будет встроен в бандл и начнёт работать.

**Никаких ручных действий в UI CRM не нужно.** Кнопки появляются автоматически после установки приложения.

### 12.4. Как webhook-эндпоинт становится доступен

Функция `handle_docusign_event` с декоратором `@frappe.whitelist(allow_guest=True)` автоматически доступна по URL:

```
https://{ваш-домен}/api/method/frappe_docusign.api.webhook.handle_docusign_event
```

Никаких роутов, nginx-конфигов, дополнительных настроек не нужно. Frappe маршрутизирует все `/api/method/` вызовы к соответствующим Python-функциям автоматически.

### 12.5. Деплой на Frappe Cloud (рекомендуемый путь)

Если CRM развёрнута на **Frappe Cloud** (frappecloud.com):

```
Шаг 1. Разработчик пушит код в GitHub-репозиторий
        └── github.com/artbot-ai/frappe_docusign

Шаг 2. В Frappe Cloud Dashboard:
        └── Sites → [твой сайт] → Apps → "Add App"
        └── Указать URL репозитория
        └── Frappe Cloud клонирует репо, ставит зависимости из requirements.txt,
            запускает `bench --site install-app` и `bench migrate`

Шаг 3. Готово. Зайди на {site}/app/docusign-settings → заполни credentials.

Шаг 4. При обновлениях кода:
        └── Разработчик делает push в GitHub
        └── В Frappe Cloud → Sites → [сайт] → "Update Available" → Deploy
        └── Или настроить auto-deploy при push в main branch
```

**Никакого SSH, никаких ручных команд.** Frappe Cloud делает всё через UI.

### 12.6. Деплой на свой сервер (self-hosted)

Если CRM на своём сервере с `bench`:

```bash
# 1. Установить приложение из GitHub
cd /home/frappe/frappe-bench
bench get-app https://github.com/artbot-ai/frappe_docusign

# 2. Установить на конкретный сайт
bench --site artbot.example.com install-app frappe_docusign

# 3. Применить миграции (создаст DocType, кастомные поля)
bench --site artbot.example.com migrate

# 4. Пересобрать JS-бандлы (подключит Client Script)
bench build --app frappe_docusign

# 5. Перезапустить сервер
bench restart

# Для обновлений:
cd apps/frappe_docusign && git pull
bench --site artbot.example.com migrate
bench build --app frappe_docusign
bench restart
```

### 12.7. Чеклист: как проверить что всё заработало

После деплоя выполни по порядку:

| #  | Проверка                                                        | Как проверить                                      |
|----|-----------------------------------------------------------------|----------------------------------------------------|
| 1  | Приложение установлено                                          | `bench --site {site} list-apps` → видишь `frappe_docusign` |
| 2  | DocuSign Settings существует                                    | Перейти на `{site}/app/docusign-settings`          |
| 3  | Кастомные поля на CRM Deal появились                            | Открыть любую сделку → прокрутить вниз → секция «DocuSign» |
| 4  | Кнопка «Отправить на подпись» видна                             | Открыть сделку со stage = "Proposal Sent"          |
| 5  | DocuSign credentials введены                                    | Заполнить DocuSign Settings, поставить enabled = ✓  |
| 6  | OAuth consent получен                                           | Открыть consent URL в браузере, нажать "Allow"     |
| 7  | Тестовая отправка работает                                      | Нажать кнопку на сделке → проверить email           |
| 8  | Webhook доходит                                                 | Подписать документ → статус сделки обновился        |

### 12.8. Что происходит «под капотом» при install-app

Для полноты картины — что делает Frappe при установке приложения:

```
bench --site {site} install-app frappe_docusign
│
├── 1. Читает hooks.py → находит DocTypes приложения
├── 2. Создаёт таблицы в MariaDB для каждого DocType (docusign_settings)
├── 3. Применяет fixtures → создаёт Custom Fields на CRM Deal
├── 4. Регистрирует whitelisted methods → доступны через /api/method/
├── 5. Регистрирует doctype_js → Client Script будет загружаться на форме CRM Deal
├── 6. Устанавливает Python-зависимости из requirements.txt
└── 7. Записывает frappe_docusign в installed_apps сайта
```

После этого — `bench build` компилирует JS в бандл, и при следующей загрузке страницы CRM Deal кнопки появятся.

---

## 13. Безопасность

- Credentials зашифрованы (Frappe Password fields)
- HMAC-верификация на webhook
- Access token не уходит на клиент
- RSA-ключ не покидает сервер
- Подписанные документы хранятся в DocuSign (не в Frappe)

---

## 14. Путь к V2 (что добавлять потом)

| Фича                                    | Когда добавлять                        |
|-----------------------------------------|----------------------------------------|
| Отдельный DocType для Envelope Log      | Когда нужно несколько конвертов на сделку |
| Хранение подписанных PDF (S3 / Frappe)  | Когда нужна автономность от DocuSign   |
| Scheduled job для «зависших» конвертов  | Когда >50 конвертов в месяц            |
| DocuSign Templates                      | Когда появятся стандартные документы    |
| Мультиподписант                         | Когда нужна подпись двух сторон        |
| Embedded signing (внутри CRM)           | Когда важен UX менеджера               |
| Генерация документов из данных CRM      | Когда будет document builder           |
