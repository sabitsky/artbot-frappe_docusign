# frappe_docusign — Руководство по установке для администратора

**Для кого:** системный администратор с SSH-доступом к серверу Frappe (Hetzner).
**Цель:** установить приложение, убедиться что всё работает, прислать отчёт.
**Время:** ~30–40 минут.

---

## Содержание

1. [Подготовка — проверка среды](#1-подготовка--проверка-среды)
2. [Установка приложения](#2-установка-приложения)
3. [Проверка через браузер](#3-проверка-через-браузер)
4. [Запуск автотестов](#4-запуск-автотестов)
5. [Запуск диагностического эндпоинта](#5-запуск-диагностического-эндпоинта)
6. [Критерии успешной установки](#6-критерии-успешной-установки)
7. [Что прислать в отчёте](#7-что-прислать-в-отчёте)
8. [Устранение неполадок](#8-устранение-неполадок)

---

## 1. Подготовка — проверка среды

Войдите на сервер и выполните команды ниже. Убедитесь, что все результаты соответствуют ожидаемым.

### 1.1 Зайти в рабочую директорию bench

```bash
cd /home/frappe/frappe-bench
```

> **Если директория другая** — найдите её командой `find /home -name "apps" -maxdepth 4 -type d 2>/dev/null` и замените путь.

### 1.2 Узнать имя сайта

```bash
bench list-sites
```

**Пример вывода:**
```
crm.yourdomain.com
```

Запомните имя сайта — оно подставляется вместо `{site}` во всех командах ниже.

### 1.3 Проверить что Frappe CRM установлена

```bash
bench --site {site} list-apps
```

**Ожидаемый вывод (список будет отличаться, главное чтобы присутствовали):**
```
frappe
erpnext         ← необязательно
crm             ← ОБЯЗАТЕЛЬНО должна быть
```

> Если `crm` отсутствует — остановитесь и сообщите. Frappe CRM должна быть установлена до установки нашего приложения.

### 1.4 Проверить версию Python

```bash
python3 --version
```

**Ожидается:** `Python 3.10.x` или выше.

### 1.5 Проверить что pip-зависимости доступны

```bash
/home/frappe/frappe-bench/env/bin/pip show PyJWT cryptography requests
```

**Ожидается:** три блока с Name/Version (точные версии неважны):
```
Name: PyJWT
Version: 2.x.x
---
Name: cryptography
Version: 4x.x.x
---
Name: requests
Version: 2.x.x
```

> Если что-то из трёх не найдено — выполните:
> ```bash
> /home/frappe/frappe-bench/env/bin/pip install "PyJWT>=2.0" "cryptography>=3.0" "requests>=2.28"
> ```

---

## 2. Установка приложения

Выполняйте команды строго по порядку. После каждой — проверяйте вывод на наличие ошибок.

### Шаг 1 — Скачать приложение с GitHub

```bash
bench get-app https://github.com/sabitsky/artbot-frappe_docusign
```

**Ожидаемый вывод (примерно):**
```
Getting frappe_docusign
Cloning into '/home/frappe/frappe-bench/apps/frappe_docusign'...
remote: Enumerating objects: ...
...
Installing frappe_docusign
```

**Признаки проблемы:** `fatal: repository not found`, `Permission denied`, `Could not resolve host`.
**Решение:** проверить доступ к GitHub с сервера: `curl -I https://github.com`

---

### Шаг 2 — Установить приложение на сайт

```bash
bench --site {site} install-app frappe_docusign
```

**Ожидаемый вывод:**
```
Installing frappe_docusign...
```

Возможны строки вида `frappe_docusign: Created CRM stages: Lead, Qualified, ...` — это нормально.

**Признак проблемы:** `App frappe_docusign is not installed`. Значит шаг 1 не завершился — повторите.

---

### Шаг 3 — Применить миграции

```bash
bench --site {site} migrate
```

Это долгая команда (~2–5 минут). Она создаёт в базе данных:
- таблицу DocuSign Settings
- кастомные поля на CRM Deal
- стадии пайплайна (Lead, Qualified, Proposal Sent, и т.д.)
- CRM Form Script с кнопками

**Ожидаемый вывод (фрагмент):**
```
Migrating frappe_docusign
frappe_docusign: Created CRM stages: Lead, Qualified, Proposal Sent, Contract Sent, Contract Signed, Onboarding
frappe_docusign: CRM Form Script created.
```

**Допустимые предупреждения (не ошибки):**
```
frappe_docusign: Skipped existing CRM stages: Lead, Qualified, ...
frappe_docusign: CRM Form Script is already up to date.
```

**Критические ошибки — требуют сообщения:**
- `Could not create CRM Stage` — смотрите раздел [8.2](#82-стадии-crm-stage-не-создаются)
- `CRM Form Script DocType not found` — CRM установлена некорректно
- Любой Python traceback (стек вызовов с `Traceback (most recent call last)`)

---

### Шаг 4 — Собрать JS-ресурсы

```bash
bench build --app frappe_docusign
```

**Ожидаемый вывод:**
```
Building frappe_docusign...
✓ Built
```

---

### Шаг 5 — Перезапустить сервер

```bash
bench restart
```

**Ожидаемый вывод:**
```
Restarting gunicorn...
Restarting workers...
```

---

### Шаг 6 — Подтвердить что приложение в списке

```bash
bench --site {site} list-apps
```

**Ожидается:** в выводе присутствует `frappe_docusign`:
```
frappe
crm
frappe_docusign    ← должна быть здесь
```

---

## 3. Проверка через браузер

Все три проверки ниже выполняются в браузере, залогинившись в Frappe CRM как System Manager (администратор).

### Проверка А — Форма настроек DocuSign

Откройте в браузере:
```
https://{site}/app/docusign-settings
```

**Ожидаемый результат:**
Загружается форма с заголовком **DocuSign Settings** и следующими полями:

| Поле | Тип |
|------|-----|
| Enabled | Чекбокс |
| Environment | Выпадающий список (Sandbox / Production) |
| Integration Key (Client ID) | Текстовое поле |
| Account ID | Текстовое поле |
| User ID | Текстовое поле |
| Base URL | Текстовое поле |
| Auth Server | Текстовое поле |
| RSA Private Key | Многострочный редактор кода |
| Webhook HMAC Secret | Поле пароля |

> **Итого: 9 полей.** Если полей меньше или страница возвращает 404 — смотрите раздел [8.1](#81-страница-docusign-settings-не-открывается).

---

### Проверка Б — Кастомные поля на CRM Deal

1. Откройте любую CRM-сделку (Deal) через меню CRM.
2. Прокрутите страницу вниз до конца.
3. Найдите свёрнутую секцию **DocuSign** (серая полоса с треугольником).
4. Разверните её кликом.

**Ожидаемый результат — внутри секции 7 полей:**

| Поле | Описание |
|------|----------|
| DocuSign Envelope ID | Пустое, только для чтения |
| DocuSign Status | Пустое, только для чтения |
| DocuSign Sent At | Пустое, только для чтения |
| DocuSign Completed At | Пустое, только для чтения |
| DocuSign Envelope Link | Пустое, только для чтения |
| DocuSign Last Error | Пустое, только для чтения |

> Если секция не появляется — смотрите раздел [8.3](#83-секция-docusign-не-появляется-на-deal).

---

### Проверка В — Кнопки DocuSign на форме

1. Откройте любую CRM-сделку.
2. Найдите поле стадии сделки (Stage или Pipeline Stage — зависит от вашей версии CRM).
3. Измените стадию на **Proposal Sent**.
4. Сохраните сделку.

**Ожидаемый результат:**
В правом верхнем углу формы появляется кнопка-группа **DocuSign** с пунктом **Send for Signing**.

> Если кнопка не появляется:
> - Проверьте, что стадия сохранилась как именно `Proposal Sent` (без опечаток).
> - Смотрите раздел [8.4](#84-кнопки-docusign-не-появляются).

---

## 4. Запуск автотестов

### 4.1 Включить тестовый режим (один раз)

```bash
bench --site {site} set-config allow_tests 1
```

Вывода нет — это нормально.

---

### 4.2 Запустить все тесты приложения

```bash
bench --site {site} run-tests --app frappe_docusign
```

Тесты работают ~3–5 минут. Это нормально — они создают временные документы в тестовой БД.

**Ожидаемый успешный вывод (в конце):**
```
Ran 42 tests in X.XXXs

OK
```

Или в более многословном формате:
```
...........................................
----------------------------------------------------------------------
Ran 42 tests in 4.312s

OK
```

Каждая точка `.` — один пройденный тест. `OK` в конце означает что все тесты прошли.

---

### 4.3 Интерпретация результатов

**Всё хорошо:**
```
OK
```

**Есть пропущенные тесты (не критично):**
```
Ran 42 tests in 4.5s

OK (skipped=2)
```

**Есть ошибки — нужно сообщить:**
```
FAILED (failures=1, errors=2)
```

В этом случае выше в выводе будут строки вида:
```
FAIL: test_valid_signature_returns_true (frappe_docusign.api.tests.test_webhook.TestVerifyHmac)
----------------------------------------------------------------------
Traceback (most recent call last):
  ...
AssertionError: False is not true
```

Скопируйте **весь вывод** команды и пришлите.

---

### 4.4 Запуск отдельных тест-модулей (если нужна диагностика)

```bash
# Тесты DocuSign Settings
bench --site {site} run-tests --app frappe_docusign \
    --module frappe_docusign.docusign.doctype.docusign_settings.test_docusign_settings

# Тесты аутентификации (JWT)
bench --site {site} run-tests --app frappe_docusign \
    --module frappe_docusign.api.tests.test_auth

# Тесты отправки конвертов
bench --site {site} run-tests --app frappe_docusign \
    --module frappe_docusign.api.tests.test_envelope

# Тесты вебхука
bench --site {site} run-tests --app frappe_docusign \
    --module frappe_docusign.api.tests.test_webhook
```

---

## 5. Запуск диагностического эндпоинта

Этот шаг нужен чтобы убедиться, что код знает правильные названия полей в вашей версии Frappe CRM. Разные версии CRM используют разные названия (`pipeline_stage` или `stage`, `email` или `contact_email`, и т.д.).

### 5.1 Получить API-токен в Frappe

1. Зайдите в Frappe → правый верхний угол → имя пользователя → **My Settings** (или **Мои настройки**).
2. Прокрутите вниз до секции **API Access**.
3. Нажмите **Generate Keys** (если ключей ещё нет).
4. Скопируйте **API Key** и **API Secret**.

### 5.2 Выполнить запрос

```bash
curl -s \
  "https://{site}/api/method/frappe_docusign.api.diagnostic.get_crm_deal_fields" \
  -H "Authorization: token {API_KEY}:{API_SECRET}" | python3 -m json.tool
```

Замените `{site}`, `{API_KEY}`, `{API_SECRET}` реальными значениями.

### 5.3 Пример вывода

```json
{
    "message": {
        "all_fields": [...],
        "stage_candidates": [
            {
                "fieldname": "pipeline_stage",
                "fieldtype": "Link",
                "label": "Pipeline Stage",
                "options": "CRM Stage",
                "reqd": false
            }
        ],
        "email_candidates": [
            {
                "fieldname": "email",
                "fieldtype": "Data",
                "label": "Email",
                "options": "Email",
                "reqd": false
            }
        ],
        "name_candidates": [
            {
                "fieldname": "lead_name",
                "fieldtype": "Data",
                "label": "Lead Name",
                "options": null,
                "reqd": true
            }
        ],
        "note": "Use stage_candidates, email_candidates, name_candidates to identify..."
    }
}
```

**Пришлите полный вывод** — особенно содержимое `stage_candidates`, `email_candidates`, `name_candidates`.

> Если команда возвращает `{"exc_type": "PermissionError"}` — значит токен неверный или у пользователя нет прав System Manager.

---

## 6. Критерии успешной установки

Установка считается **полностью успешной**, если выполнены ВСЕ пункты:

| # | Критерий | Как проверить |
|---|----------|---------------|
| 1 | `frappe_docusign` есть в `list-apps` | Шаг 6 раздела 2 |
| 2 | Migrate прошёл без Python traceback | Вывод шага 3 |
| 3 | Страница `/app/docusign-settings` открывается с 9 полями | Проверка А |
| 4 | Секция DocuSign с 7 полями видна на CRM Deal | Проверка Б |
| 5 | Кнопка «Send for Signing» появляется на стадии «Proposal Sent» | Проверка В |
| 6 | Все тесты: `OK` в конце вывода | Раздел 4 |
| 7 | Диагностический JSON получен и отправлен | Раздел 5 |

---

## 7. Что прислать в отчёте

После завершения пришлите следующее:

### 7.1 Обязательно

```
1. Вывод: bench --site {site} list-apps
2. Вывод команды migrate (шаг 3) — можно вставить текст или прислать скриншот
3. Результат трёх браузерных проверок (А, Б, В) — прошли / не прошли
4. Вывод запуска тестов (bench run-tests) — полностью, включая последние строки
5. Полный JSON из диагностического эндпоинта
```

### 7.2 Если что-то не работает

```
6. Полный текст ошибки (traceback / сообщение об ошибке)
7. На каком конкретно шаге возникла проблема
```

---

## 8. Устранение неполадок

### 8.1 Страница DocuSign Settings не открывается

**Симптом:** браузер показывает 404 или «Not Found».

**Причина:** миграции не применились или сервер не перезапущен.

**Решение:**
```bash
bench --site {site} migrate
bench restart
```

---

### 8.2 Стадии CRM Stage не создаются

**Симптом:** в выводе migrate есть строка:
```
frappe_docusign: Could not create CRM Stage 'Proposal Sent': ...
```

**Причина:** в вашей версии Frappe CRM поле `name` у CRM Stage не является первичным ключом, или DocType требует дополнительных обязательных полей.

**Решение — создать стадии вручную:**

1. Откройте в браузере: `https://{site}/app/crm-stage`
2. Создайте следующие стадии по одной, нажимая «Add CRM Stage»:
   - `Lead`
   - `Qualified`
   - `Proposal Sent`
   - `Contract Sent`
   - `Contract Signed`
   - `Onboarding`

---

### 8.3 Секция DocuSign не появляется на Deal

**Симптом:** открываете Deal, прокручиваете вниз — секции DocuSign нет.

**Причина 1:** ресурсы не пересобраны.
```bash
bench build --app frappe_docusign
bench restart
```

**Причина 2:** fixtures не применились. Проверьте:
```bash
bench --site {site} console
# Внутри консоли:
frappe.db.exists("Custom Field", "CRM Deal-docusign_section")
# Должно вернуть: 'CRM Deal-docusign_section'
# exit()
```

Если вернуло `None`:
```bash
bench --site {site} migrate
```

---

### 8.4 Кнопки DocuSign не появляются

**Симптом:** стадия сделки — `Proposal Sent`, но кнопки в правом верхнем углу нет.

**Шаг 1 — проверить CRM Form Script в базе:**
```bash
bench --site {site} console
frappe.db.exists("CRM Form Script", "DocuSign Buttons - CRM Deal")
# Должно вернуть: 'DocuSign Buttons - CRM Deal'
# exit()
```

Если вернуло `None` — Form Script не создался:
```bash
bench --site {site} migrate
```

**Шаг 2 — проверить что Form Script включён:**

1. Откройте `https://{site}/app/crm-form-script`
2. Найдите запись **DocuSign Buttons - CRM Deal**
3. Убедитесь что чекбокс **Enabled** стоит

**Шаг 3 — сбросить кеш браузера:**

Нажмите `Ctrl+Shift+R` (или `Cmd+Shift+R` на Mac) на странице CRM Deal.

---

### 8.5 Ошибка при запуске тестов: ImportError

**Симптом:**
```
ImportError: No module named 'jwt'
```
или
```
ImportError: No module named 'cryptography'
```

**Решение:**
```bash
/home/frappe/frappe-bench/env/bin/pip install "PyJWT>=2.0" "cryptography>=3.0" "requests>=2.28"
bench restart
```

---

### 8.6 Обновление приложения после изменений в коде

Если в будущем нужно обновить приложение после новых коммитов в GitHub:

```bash
cd /home/frappe/frappe-bench/apps/frappe_docusign
git pull

cd /home/frappe/frappe-bench
bench --site {site} migrate
bench build --app frappe_docusign
bench restart
```

Команда `migrate` автоматически обновит CRM Form Script из нового JS-файла.

---

*Если возникают вопросы не описанные в этом документе — фиксируйте точный текст ошибки и шаг, на котором остановились.*
