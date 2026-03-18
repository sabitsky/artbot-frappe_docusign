# Spec: CRM Lead → Deal → Contract → Payment flow

**Версия:** 2.2
**Дата:** 2026-03-18
**Статус:** Ready for implementation
**Изменения v2.2:** Убраны избыточные Deal-статусы (Qualification, Paid). Исправлены баги: `on_change` → `validate` для DocuSign hook, убран `frappe.db.commit()` из whitelisted-функции, webhook возвращает JSON вместо throw, добавлены fallback-ы для совместимости Next.js 15+ и Node.js <17.3.
**Изменения v2.1:** Разделение flow между CRM Lead и CRM Deal. Кастомные поля и DocuSign-хуки на Deal. Статусы приведены в соответствие с архитектурой Frappe CRM.

---

## Контекст

Когда пользователь регистрируется на сайте (Next.js) через email или Google — в Frappe CRM автоматически создаётся лид в статусе `New`. Если лид с таким email уже существует — дубль не создаётся, возвращается ID существующего.

Frappe CRM разделяет Lead (потенциальный клиент) и Deal (конкретная сделка). Lead отвечает за захват и квалификацию. После квалификации Lead конвертируется в Deal через встроенную кнопку «Convert to Deal» (при этом создаются Contact + Organization). Весь коммерческий pipeline живёт на Deal.

**Стек:**
- Backend CRM: Frappe (self-hosted), приложение `frappe_docusign`
- Frontend/сайт: Next.js (App Router)
- Auth на сайте: NextAuth.js или Supabase Auth
- Юридический слой: DocuSign (contracts + GDPR consent)
- Коммерческий слой: Holded (invoicing) + Stripe (payments)
- Налоговый слой: внешняя gestoría (работает из своего софта, получает данные из Holded)

---

## Что нужно реализовать

### Lead (захват + квалификация)
1. **Frappe:** новый файл `frappe_docusign/api/crm_lead.py` — whitelisted endpoint
2. **Frappe:** тесты `frappe_docusign/api/tests/test_crm_lead.py`
3. **Next.js:** утилита `lib/crm.ts` — server-side вызов Frappe API
4. **Next.js:** вызов из auth callback при регистрации нового пользователя
5. **Next.js:** middleware для сбора UTM-параметров в cookie
6. **Frappe:** создать служебного пользователя + API Key
7. **Frappe:** настроить Lead Statuses (см. Часть 1.4)

### Deal (коммерческий pipeline)
8. **Frappe:** настроить Deal Statuses (см. Часть 1.5)
9. **Frappe:** кастомные поля на CRM Deal: `service_type`, `preferred_language`, `docusign_envelope_id`
10. **Frappe:** автоматическая отправка DocuSign envelope при переходе Deal в `Contract Sent`
11. **Frappe:** webhook endpoint для получения статуса подписания из DocuSign

---

## Часть 1: Frappe

### 1.1 Новый файл `frappe_docusign/api/crm_lead.py`

Создать файл по пути `frappe_docusign/api/crm_lead.py` со следующим содержимым:

```python
"""
CRM Lead creation endpoint — called from the website after user registration.

Whitelisted, requires API Key authentication (not guest).
Deduplicates by email: returns existing lead ID without creating a duplicate.

Call via:
    POST /api/method/frappe_docusign.api.crm_lead.create_lead
    Authorization: token {api_key}:{api_secret}
    Content-Type: application/x-www-form-urlencoded

    email=user@example.com&first_name=Ivan&last_name=Petrov&source=google
    &utm_source=google&utm_medium=cpc&utm_campaign=spring2026
"""
import frappe


@frappe.whitelist(allow_guest=False)
def create_lead(
    email: str,
    first_name: str = "",
    last_name: str = "",
    source: str = "",
    utm_source: str = "",
    utm_medium: str = "",
    utm_campaign: str = "",
) -> dict:
    """
    Create a CRM Lead after website registration.

    Returns:
        {"lead": "CRM-LEAD-XXXX", "created": True}   — new lead created
        {"lead": "CRM-LEAD-XXXX", "created": False}  — duplicate found, returned as-is
    """
    email = (email or "").strip().lower()
    if not email:
        frappe.throw("Email is required.", frappe.ValidationError)

    # 1. Deduplication — check by email (case-insensitive, already normalised above)
    existing = frappe.db.get_value("CRM Lead", {"email": email}, "name")
    if existing:
        return {"lead": existing, "created": False}

    # 2. Build UTM note (stored in `notes` until custom UTM fields are added)
    utm_parts = {
        "utm_source": utm_source,
        "utm_medium": utm_medium,
        "utm_campaign": utm_campaign,
    }
    utm_note = " ".join(f"{k}={v}" for k, v in utm_parts.items() if v)

    # 3. Resolve lead_name: prefer full name, fall back to email
    full_name = f"{first_name} {last_name}".strip()

    # 4. Create the lead
    lead = frappe.new_doc("CRM Lead")
    lead.first_name = first_name
    lead.last_name = last_name
    lead.lead_name = full_name or email
    lead.email = email
    lead.source = _map_source(source)
    lead.status = "New"
    if utm_note:
        lead.notes = utm_note

    lead.insert(ignore_permissions=True)
    # NOTE: не вызываем frappe.db.commit() — Frappe автоматически коммитит
    # после завершения whitelisted-функции. Явный commit ломает транзакционность
    # и тестовую изоляцию.

    return {"lead": lead.name, "created": True}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _map_source(source: str) -> str:
    """
    Map website registration source to a Frappe CRM Lead source value.

    IMPORTANT: verify allowed values via:
        frappe.get_meta("CRM Lead").get_field("source").options
    If "Website" or "Social Media" are not in the list — update this mapping.
    """
    mapping = {
        "google": "Social Media",
        "email": "Website",
    }
    return mapping.get((source or "").strip().lower(), "Website")
```

**Никаких изменений в `hooks.py` не требуется** для этого endpoint — `@frappe.whitelist` достаточно для регистрации.

---

### 1.2 Проверка полей CRM Lead

Перед финальным деплоем выполнить в `bench console`:

```python
# Убедиться, что поля существуют с именно такими именами
meta = frappe.get_meta("CRM Lead")
print([f.fieldname for f in meta.fields])

# Убедиться, что source имеет нужные опции
print(frappe.get_meta("CRM Lead").get_field("source").options)

# Убедиться, что status "New" существует
print(frappe.get_meta("CRM Lead").get_field("status").options)
```

Ожидаемые поля: `email`, `first_name`, `last_name`, `lead_name`, `source`, `status`, `notes`.
Если поле называется иначе (например `email_id` вместо `email`) — обновить `crm_lead.py` соответственно.

---

### 1.3 Тесты `frappe_docusign/api/tests/test_crm_lead.py`

Создать файл:

```python
"""
Tests for frappe_docusign.api.crm_lead.create_lead

Run:
    bench --site {site} run-tests --app frappe_docusign \
        --module frappe_docusign.api.tests.test_crm_lead
"""
import frappe
from frappe.tests.utils import FrappeTestCase

from frappe_docusign.api.crm_lead import create_lead, _map_source

_TEST_EMAIL = "crm_lead_test_user@example.com"


class TestCreateLead(FrappeTestCase):

    def tearDown(self):
        # Clean up any leads created during tests
        leads = frappe.get_all("CRM Lead", filters={"email": _TEST_EMAIL}, pluck="name")
        for name in leads:
            frappe.delete_doc("CRM Lead", name, force=True)
        frappe.db.commit()

    # ------------------------------------------------------------------
    # Happy path
    # ------------------------------------------------------------------

    def test_creates_lead_and_returns_created_true(self):
        result = create_lead(
            email=_TEST_EMAIL,
            first_name="Ivan",
            last_name="Petrov",
            source="email",
        )
        self.assertTrue(result["created"])
        self.assertTrue(frappe.db.exists("CRM Lead", result["lead"]))

    def test_lead_has_correct_email(self):
        result = create_lead(email=_TEST_EMAIL)
        doc = frappe.get_doc("CRM Lead", result["lead"])
        self.assertEqual(doc.email, _TEST_EMAIL)

    def test_lead_status_is_new(self):
        result = create_lead(email=_TEST_EMAIL)
        doc = frappe.get_doc("CRM Lead", result["lead"])
        self.assertEqual(doc.status, "New")

    def test_lead_name_uses_full_name_when_provided(self):
        result = create_lead(email=_TEST_EMAIL, first_name="Ivan", last_name="Petrov")
        doc = frappe.get_doc("CRM Lead", result["lead"])
        self.assertEqual(doc.lead_name, "Ivan Petrov")

    def test_lead_name_falls_back_to_email_when_no_name(self):
        result = create_lead(email=_TEST_EMAIL)
        doc = frappe.get_doc("CRM Lead", result["lead"])
        self.assertEqual(doc.lead_name, _TEST_EMAIL)

    def test_utm_stored_in_notes(self):
        result = create_lead(
            email=_TEST_EMAIL,
            utm_source="google",
            utm_medium="cpc",
            utm_campaign="spring2026",
        )
        doc = frappe.get_doc("CRM Lead", result["lead"])
        self.assertIn("utm_source=google", doc.notes)
        self.assertIn("utm_medium=cpc", doc.notes)
        self.assertIn("utm_campaign=spring2026", doc.notes)

    def test_no_notes_when_no_utm(self):
        result = create_lead(email=_TEST_EMAIL)
        doc = frappe.get_doc("CRM Lead", result["lead"])
        self.assertFalse(doc.notes)

    # ------------------------------------------------------------------
    # Deduplication
    # ------------------------------------------------------------------

    def test_duplicate_email_returns_existing_lead(self):
        r1 = create_lead(email=_TEST_EMAIL, first_name="Ivan")
        r2 = create_lead(email=_TEST_EMAIL, first_name="Ivan2")
        self.assertEqual(r1["lead"], r2["lead"])
        self.assertFalse(r2["created"])

    def test_dedup_is_case_insensitive(self):
        r1 = create_lead(email=_TEST_EMAIL.lower())
        r2 = create_lead(email=_TEST_EMAIL.upper())
        self.assertEqual(r1["lead"], r2["lead"])
        self.assertFalse(r2["created"])

    def test_only_one_lead_exists_after_duplicate_call(self):
        create_lead(email=_TEST_EMAIL)
        create_lead(email=_TEST_EMAIL)
        count = frappe.db.count("CRM Lead", {"email": _TEST_EMAIL})
        self.assertEqual(count, 1)

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def test_empty_email_raises_validation_error(self):
        with self.assertRaises(frappe.ValidationError):
            create_lead(email="")

    def test_whitespace_only_email_raises_validation_error(self):
        with self.assertRaises(frappe.ValidationError):
            create_lead(email="   ")

    # ------------------------------------------------------------------
    # Source mapping
    # ------------------------------------------------------------------

    def test_google_source_maps_to_social_media(self):
        self.assertEqual(_map_source("google"), "Social Media")

    def test_email_source_maps_to_website(self):
        self.assertEqual(_map_source("email"), "Website")

    def test_unknown_source_maps_to_website(self):
        self.assertEqual(_map_source("unknown_provider"), "Website")

    def test_empty_source_maps_to_website(self):
        self.assertEqual(_map_source(""), "Website")

    def test_source_mapping_is_case_insensitive(self):
        self.assertEqual(_map_source("GOOGLE"), "Social Media")
```

Запуск тестов:

```bash
bench --site {site} set-config allow_tests 1
bench --site {site} run-tests --app frappe_docusign \
    --module frappe_docusign.api.tests.test_crm_lead
```

---

### 1.4 Lead Statuses

> **Справка:** Frappe CRM хранит статусы в отдельных doctype — `CRM Lead Status` и `CRM Deal Status`. Управление: Desk → CRM Lead Status (список). Дефолтные статусы создаются при установке в `install.py`. Для условного отображения подмножества статусов используется Form Script (см. [Custom Statuses docs](https://docs.frappe.io/crm/custom-statuses)).

**Дефолтные статусы Frappe CRM (из install.py):**

| # | Status | Color | Что это значит | Как попадает | Как выходит |
|---|--------|-------|---------------|-------------|-------------|
| 1 | New | gray | Человек зарегистрировался на сайте, но с ним ещё никто не связывался | Автоматически при регистрации (endpoint `create_lead`) | Sales берёт лид в работу → `Contacted` |
| 2 | Contacted | orange | Sales связался с клиентом (email, звонок, WhatsApp), выясняет потребность | Sales вручную переводит из `New` | Готов → `Qualified`. Не готов сейчас → `Nurture`. Не подходит → `Unqualified` |
| 3 | Nurture | blue | Клиент заинтересован, но не готов прямо сейчас. Нужен подогрев | Sales вручную переводит из `Contacted` | Клиент созрел → `Qualified`. Потерял интерес → `Unqualified` |
| 4 | Qualified | green | Потребность подтверждена, клиент готов к услуге. Промежуточный статус перед конверсией | Sales вручную из `Contacted` или `Nurture` | Sales нажимает «Convert to Deal» → создаётся Deal, лид получает флаг `converted` |
| 5 | Unqualified | red | Не целевой: нет бюджета, не та локация, не та услуга | Sales вручную из любого статуса | Терминальный (можно реактивировать вручную) |
| 6 | Junk | purple | Спам, тестовая регистрация, бот, дубль | Sales вручную из любого статуса | Терминальный |

**Решение для ArtBot: оставляем дефолтные без изменений.**

Дефолтные Lead Statuses Frappe CRM полностью покрывают наш pre-sale flow. Нет причин менять или добавлять новые. Коммерческие этапы (контракт, оплата, доставка услуги) живут на Deal.

**Переходы Lead и ответственные:**

| Переход | Кто делает | Что происходит |
|---------|-----------|----------------|
| `New` → `Contacted` | Sales (вручную) | Sales связался с клиентом, выясняет потребность |
| `Contacted` → `Nurture` | Sales (вручную) | Клиент заинтересован, но не готов сейчас. Требуется подогрев |
| `Contacted` → `Qualified` | Sales (вручную) | Потребность подтверждена, клиент готов к услуге |
| `Nurture` → `Qualified` | Sales (вручную) | Подогретый лид созрел |
| `Qualified` → **Convert to Deal** | Sales (кнопка в UI) | Встроенная конверсия Frappe CRM. Создаётся Contact, Organization, Deal |
| Любой → `Unqualified` | Sales (вручную) | Не целевой клиент (нет бюджета, не та локация и т.д.) |
| Любой → `Junk` | Sales (вручную) | Спам, тестовая регистрация, дубль |

---

### 1.5 Deal Statuses

**Дефолтные статусы Frappe CRM (из install.py):**

| # | Status | Color |
|---|--------|-------|
| 1 | Qualification | gray |
| 2 | Demo/Making | orange |
| 3 | Proposal/Quotation | blue |
| 4 | Negotiation | yellow |
| 5 | Ready to Close | purple |
| 6 | Won | green |
| 7 | Lost | red |

**Решение для ArtBot: заменяем дефолтные на кастомные.**

Дефолтные Deal Statuses заточены под продуктовые/SaaS-продажи (Demo, Negotiation). Сервисная модель ArtBot требует другого pipeline: контракт → оплата → оказание услуги.

**Кастомные Deal Statuses для ArtBot:**

| # | Status | Color | Что это значит | Как попадает | Как выходит |
|---|--------|-------|---------------|-------------|-------------|
| 1 | New | gray | Deal только что создан из Lead. Ops должен заполнить `service_type` и `preferred_language` | Автоматически при конверсии Lead → Deal (кнопка «Convert to Deal») | Ops заполнил поля, переводит вручную → `Contract Sent` |
| 2 | Contract Sent | orange | Контракт и GDPR-согласие отправлены клиенту на подпись. Ждём | Ops вручную из `New`. В момент перехода Frappe автоматически отправляет DocuSign envelope | DocuSign webhook → `Contract Signed`. Клиент отказался → `Lost` |
| 3 | Contract Signed | blue | Клиент подписал оба документа. Можно выставлять счёт | Автоматически (DocuSign webhook `completed`) | Ops создаёт invoice в Holded, переводит вручную → `Invoice Sent` |
| 4 | Invoice Sent | yellow | Счёт выставлен, Stripe payment link отправлен. Ждём оплату | Ops вручную из `Contract Signed` | Оплата подтверждена → `In Progress`. Не заплатил → `Lost` |
| 5 | In Progress | purple | Деньги получены, услуга оказывается | Ops вручную из `Invoice Sent` после подтверждения оплаты | Услуга оказана → `Won`. Что-то пошло не так → `Lost` |
| 6 | Won | green | Услуга полностью оказана, кейс закрыт успешно | Ops вручную из `In Progress` | Терминальный |
| 7 | Lost | red | Отказ, неоплата, отмена на любом этапе | Ops/Sales вручную из любого статуса | Терминальный (можно реактивировать если клиент вернулся) |

**Создание:** Desk → CRM Deal Status → удалить дефолтные (Qualification, Demo/Making, Proposal/Quotation, Negotiation, Ready to Close) → создать кастомные (New, Contract Sent, Contract Signed, Invoice Sent, In Progress). Статусы Won, Lost оставить.

**Переходы Deal и ответственные:**

| Переход | Кто делает | Что происходит |
|---------|-----------|----------------|
| `New` → `Contract Sent` | Ops (вручную) | **Предусловие:** заполнены `service_type` и `preferred_language`. **Триггер:** Frappe автоматически отправляет DocuSign envelope |
| `Contract Sent` → `Contract Signed` | **Автоматически** | DocuSign webhook при подписании обоих документов |
| `Contract Signed` → `Invoice Sent` | Ops (вручную) | Ops создаёт invoice в Holded, отправляет Stripe payment link клиенту |
| `Invoice Sent` → `In Progress` | Ops (вручную) | Оплата подтверждена в Holded, работа по услуге начата |
| `In Progress` → `Won` | Ops (вручную) | Услуга оказана, кейс закрыт успешно |
| Любой → `Lost` | Sales/Ops (вручную) | Клиент отказался на любом этапе |

> В будущих итерациях: Stripe webhook → автоматический переход `Invoice Sent` → `In Progress`.

---

### 1.6 Кастомные поля на CRM Deal

Добавить через `Customize Form → CRM Deal`:

| Поле | Тип | Описание |
|------|-----|----------|
| `service_type` | Select | Опции: `Immigration`, `Tax Consulting`, `Sworn Translation`, `Insurance`. Определяет шаблон договора (когда появятся раздельные шаблоны) |
| `preferred_language` | Select | Опции: `EN`, `ES`. Определяет язык envelope в DocuSign |
| `docusign_envelope_id` | Data (read-only) | ID envelope, заполняется автоматически после отправки |

Поля `service_type` и `preferred_language` заполняются вручную оператором (ops) на этапе `New`, до перевода Deal в `Contract Sent`.

> **Почему на Deal, а не на Lead:** Lead — это ещё не клиент, а потенциальный контакт. Один Lead может породить несколько Deal (например, сначала Immigration, потом Tax Consulting). Тип услуги, язык документов и DocuSign envelope привязаны к конкретной сделке, не к контакту.

---

### 1.7 Конверсия Lead → Deal

Конверсия выполняется вручную через встроенный UI Frappe CRM:

1. Sales квалифицировал лид → статус Lead = `Qualified`
2. Sales нажимает кнопку **«Convert to Deal»** на странице Lead
3. Frappe CRM предлагает:
   - Создать новый Contact + Organization (по данным из Lead)
   - Или выбрать существующие, если они уже есть
4. Создаётся CRM Deal в статусе `New`
5. Lead получает флаг `converted` и исчезает из основного списка лидов

**Автоматизировать конверсию не нужно.** Это точка принятия решения sales-менеджером, и она должна быть осознанной.

---

### 1.8 Создание служебного пользователя в Frappe

Выполнить один раз вручную на Frappe (или через bench console):

1. **Создать пользователя:** `Settings → Users → New`
   - Email: `website-integration@internal`
   - Full Name: `Website Integration`
   - Role: добавить роль с правом `create` на `CRM Lead` (или использовать системную роль `CRM User`)
   - Enabled: Yes

2. **Сгенерировать API Key:**
   - Открыть карточку пользователя → кнопка `Generate Keys` (или `API Access`)
   - Скопировать `API Key` и `API Secret`

3. **Сохранить в `.env` Next.js:**
   ```
   FRAPPE_URL=https://crm.yourdomain.com
   FRAPPE_API_KEY=<скопированный api key>
   FRAPPE_API_SECRET=<скопированный api secret>
   ```

---

### 1.9 Ручная проверка endpoint через curl

```bash
curl -X POST https://crm.yourdomain.com/api/method/frappe_docusign.api.crm_lead.create_lead \
  -H "Authorization: token API_KEY:API_SECRET" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "email=test@example.com&first_name=Test&last_name=User&source=email"

# Ожидаемый ответ (новый лид):
# {"message": {"lead": "CRM-LEAD-00001", "created": true}}

# Повторный запрос — дедупликация:
# {"message": {"lead": "CRM-LEAD-00001", "created": false}}
```

> Frappe оборачивает ответ `@whitelist` функций в `{"message": ...}`.
> Поэтому на стороне Next.js читать `data.message.lead`, а не `data.lead`.

---

## Часть 2: Next.js

### 2.1 ENV переменные

В `.env.local` (и на хостинге через dashboard):

```env
FRAPPE_URL=https://crm.yourdomain.com
FRAPPE_API_KEY=your_frappe_api_key
FRAPPE_API_SECRET=your_frappe_api_secret
```

Эти переменные **не должны** иметь префикс `NEXT_PUBLIC_` — они используются только server-side.

---

### 2.2 Утилита `lib/crm.ts`

```typescript
// lib/crm.ts

export interface RegisterLeadParams {
  email: string
  first_name?: string
  last_name?: string
  source: "email" | "google" | string
  utm_source?: string
  utm_medium?: string
  utm_campaign?: string
}

export interface RegisterLeadResult {
  lead: string
  created: boolean
}

/**
 * Registers a new user as a CRM Lead in Frappe.
 * Must be called server-side only (uses secret env vars).
 * Never throws — logs errors and returns null so auth flow is not blocked.
 */
export async function registerLeadInCRM(
  params: RegisterLeadParams
): Promise<RegisterLeadResult | null> {
  const { FRAPPE_URL, FRAPPE_API_KEY, FRAPPE_API_SECRET } = process.env

  if (!FRAPPE_URL || !FRAPPE_API_KEY || !FRAPPE_API_SECRET) {
    console.error("[CRM] Missing FRAPPE_URL / FRAPPE_API_KEY / FRAPPE_API_SECRET env vars")
    return null
  }

  const body = new URLSearchParams()
  body.set("email", params.email.toLowerCase().trim())
  body.set("first_name", params.first_name ?? "")
  body.set("last_name", params.last_name ?? "")
  body.set("source", params.source ?? "email")
  body.set("utm_source", params.utm_source ?? "")
  body.set("utm_medium", params.utm_medium ?? "")
  body.set("utm_campaign", params.utm_campaign ?? "")

  try {
    const res = await fetch(
      `${FRAPPE_URL}/api/method/frappe_docusign.api.crm_lead.create_lead`,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/x-www-form-urlencoded",
          Authorization: `token ${FRAPPE_API_KEY}:${FRAPPE_API_SECRET}`,
        },
        body: body.toString(),
        // Не блокировать auth поток дольше 5 секунд
        // AbortSignal.timeout() доступен с Node.js 17.3+
        // Для более ранних версий: используйте AbortController + setTimeout
        signal: AbortSignal.timeout?.(5000) ?? (() => {
          const ctrl = new AbortController();
          setTimeout(() => ctrl.abort(), 5000);
          return ctrl.signal;
        })(),
      }
    )

    if (!res.ok) {
      const text = await res.text()
      console.error(`[CRM] Frappe returned ${res.status}: ${text}`)
      return null
    }

    // Frappe оборачивает ответ в { message: ... }
    const data = await res.json()
    return data.message as RegisterLeadResult
  } catch (err) {
    console.error("[CRM] Failed to register lead:", err)
    return null
  }
}
```

---

### 2.3 Вызов при регистрации

#### Вариант A — NextAuth.js

```typescript
// app/api/auth/[...nextauth]/route.ts
import NextAuth from "next-auth"
import GoogleProvider from "next-auth/providers/google"
import CredentialsProvider from "next-auth/providers/credentials"
import { registerLeadInCRM } from "@/lib/crm"
import { getUtmFromCookie } from "@/lib/utm"  // см. 2.5

export const { handlers, auth, signIn, signOut } = NextAuth({
  providers: [
    GoogleProvider({ /* ... */ }),
    CredentialsProvider({ /* ... */ }),
  ],

  events: {
    async signIn({ user, account, isNewUser }) {
      // Срабатывает только при первой регистрации
      if (!isNewUser) return

      const [firstName, ...rest] = (user.name ?? "").split(" ")
      const lastName = rest.join(" ")
      const utm = await getUtmFromCookie()  // async в Next.js 15+ (см. 2.5)

      await registerLeadInCRM({
        email: user.email!,
        first_name: firstName,
        last_name: lastName,
        source: account?.provider ?? "email",
        ...utm,
      })
    },
  },
})
```

> `isNewUser` доступен только при использовании адаптера БД (database adapter).
> Без адаптера — проверять самостоятельно: при создании пользователя в БД вызывать `registerLeadInCRM`.

#### Вариант B — Supabase Auth

```typescript
// app/api/auth/callback/route.ts (или в middleware)
import { createServerClient } from "@supabase/ssr"
import { registerLeadInCRM } from "@/lib/crm"

// В server action или route handler после supabase.auth.signUp():
const { data, error } = await supabase.auth.signUp({ email, password })

if (!error && data.user) {
  const [firstName, ...rest] = (data.user.user_metadata?.full_name ?? "").split(" ")
  await registerLeadInCRM({
    email: data.user.email!,
    first_name: firstName,
    last_name: rest.join(" "),
    source: "email",
  })
}

// При Google OAuth — в обработчике callback:
// data.user.app_metadata.provider === "google"
```

---

### 2.4 API Route (опционально — только если нужен вызов с клиента)

Если по каким-то причинам нужно вызывать из браузера (не рекомендуется):

```typescript
// app/api/crm/register-lead/route.ts
import { NextRequest, NextResponse } from "next/server"
import { registerLeadInCRM } from "@/lib/crm"

export async function POST(req: NextRequest) {
  const body = await req.json()
  const result = await registerLeadInCRM(body)
  return NextResponse.json(result ?? { error: "CRM unavailable" }, {
    status: result ? 200 : 503,
  })
}
```

**Предпочтительный вариант — вызов напрямую из server-side кода** (events, server actions, route handlers), без этого промежуточного route.

---

### 2.5 Сбор UTM-параметров `lib/utm.ts`

```typescript
// lib/utm.ts
import { cookies } from "next/headers"

const UTM_COOKIE = "utm_data"
const UTM_PARAMS = ["utm_source", "utm_medium", "utm_campaign"] as const

export interface UtmData {
  utm_source?: string
  utm_medium?: string
  utm_campaign?: string
}

/** Read UTM data from cookie (server-side only) */
// NOTE: в Next.js 15+ cookies() — async. Если используется Next.js 14, можно убрать await.
export async function getUtmFromCookie(): Promise<UtmData> {
  const cookieStore = await cookies()
  const raw = cookieStore.get(UTM_COOKIE)?.value
  if (!raw) return {}
  try {
    return JSON.parse(raw) as UtmData
  } catch {
    return {}
  }
}
```

Сохранять UTM в cookie при первом визите — в middleware:

```typescript
// middleware.ts
import { NextRequest, NextResponse } from "next/server"

const UTM_COOKIE = "utm_data"
const UTM_PARAMS = ["utm_source", "utm_medium", "utm_campaign"]

export function middleware(req: NextRequest) {
  const res = NextResponse.next()
  const url = req.nextUrl

  // Если есть UTM в URL и ещё нет cookie — сохранить
  const hasUtm = UTM_PARAMS.some((p) => url.searchParams.has(p))
  const alreadySet = req.cookies.has(UTM_COOKIE)

  if (hasUtm && !alreadySet) {
    const utm: Record<string, string> = {}
    UTM_PARAMS.forEach((p) => {
      const v = url.searchParams.get(p)
      if (v) utm[p] = v
    })
    res.cookies.set(UTM_COOKIE, JSON.stringify(utm), {
      maxAge: 60 * 60 * 24 * 30,  // 30 дней
      httpOnly: true,
      sameSite: "lax",
    })
  }

  return res
}

export const config = {
  matcher: ["/((?!api|_next/static|_next/image|favicon.ico).*)"],
}
```

---

## Часть 3: Полный поток данных (регистрация → лид)

```
Пользователь регистрируется на сайте
         │
         ├─ (middleware) UTM из URL → cookie "utm_data"
         │
         ▼
auth callback / signIn event / server action
         │
         ├─ isNewUser? (или первый signUp?)
         │         └─ NO → пропустить
         │         └─ YES ↓
         │
         ▼
registerLeadInCRM({email, name, source, ...utm})   [server-side, lib/crm.ts]
         │
         │  POST /api/method/frappe_docusign.api.crm_lead.create_lead
         │  Authorization: token KEY:SECRET
         │
         ▼
Frappe: create_lead()
         │
         ├─ email уже есть в CRM Lead?
         │         └─ YES → return {lead: "CRM-LEAD-0001", created: false}
         │         └─ NO  ↓
         │
         ├─ frappe.new_doc("CRM Lead")
         ├─ status = "New", source = mapped, notes = utm
         ├─ lead.insert()
         └─ return {lead: "CRM-LEAD-0002", created: true}
         │
         ▼
registerLeadInCRM возвращает result | null
Ошибка CRM НЕ блокирует auth flow пользователя
```

---

## Часть 4: Чеклист после деплоя (регистрация → лид)

### Frappe (выполнить на сервере)

- [ ] Убедиться что файл `frappe_docusign/api/crm_lead.py` попал в репозиторий и задеплоен
- [ ] `bench --site {site} migrate` (на всякий случай)
- [ ] Проверить поля CRM Lead через bench console (см. 1.2)
- [ ] Если `source` значения не совпадают — обновить `_map_source()` в `crm_lead.py`
- [ ] Создать пользователя `website-integration@internal` и сгенерировать API Keys
- [ ] Выдать пользователю права на создание CRM Lead
- [ ] Проверить endpoint через curl (см. 1.9)
- [ ] Запустить тесты
- [ ] Проверить что Lead Statuses дефолтные на месте (New, Contacted, Nurture, Qualified, Unqualified, Junk)
- [ ] Настроить Deal Statuses (см. 1.5): удалить ненужные дефолтные, создать кастомные
- [ ] Добавить кастомные поля на CRM Deal (см. 1.6)

### Next.js

- [ ] Добавить ENV: `FRAPPE_URL`, `FRAPPE_API_KEY`, `FRAPPE_API_SECRET`
- [ ] Создать `lib/crm.ts` (см. 2.2)
- [ ] Создать `lib/utm.ts` (см. 2.5)
- [ ] Обновить `middleware.ts` для сохранения UTM в cookie (см. 2.5)
- [ ] Добавить вызов `registerLeadInCRM` в auth callback (см. 2.3)
- [ ] Зарегистрировать тестового пользователя → проверить в Frappe CRM что лид появился
- [ ] Зарегистрировать с тем же email снова → убедиться что дубль НЕ создался

---

## Часть 5: Что НЕ менять

- `install.py` — не нужны изменения
- Существующие тесты — не трогать
- DocuSign Settings DocType — не трогать (используется как есть для отправки envelopes)
- Lead Statuses — оставить дефолтные Frappe CRM

---

## Часть 6: Коммерческий flow (Deal → оплата)

### 6.1 Полный поток

```
        CRM Lead               CRM Deal (Frappe)              DOCUSIGN              HOLDED + STRIPE
        ────────               ─────────────────              ────────              ───────────────

  Lead: New
     │
  Sales квалифицирует
     │
  Lead: Qualified
     │
  «Convert to Deal» ──►  Deal: New
  (создаётся Contact,         │
   Organization)          Ops заполняет:
                          service_type,
                          preferred_language
                               │
                          Ops переводит в
                          Contract Sent
                               │
                               │ [АВТОМАТИЧЕСКИ]
                               │ Frappe validate hook
                               │ отправляет DocuSign envelope:
                               │   • Док 1: Договор (шаблон)
                               │   • Док 2: GDPR-согласие
                               │   • Язык: preferred_language
                               │   • Получатель: email контакта
                               │
                               │ docusign_envelope_id
                               │ сохраняется на Deal
                               │                        ──────►  Envelope отправлен
                               │                                  (договор + GDPR)
                               │                                       │
                               │                                  Клиент подписывает
                               │                                  оба документа
                               │                                       │
                               │                                  completed
                               │◄────────── webhook ──────────────────┘
                               │
                          Deal: Contract Signed
                               │
                          [ВРУЧНУЮ] Ops создаёт
                          invoice в Holded:
                            • Контакт: тот же email
                            • Сумма: по прайсу
                            • Stripe payment link   ──────────►  Invoice + Stripe link
                               │                                  отправлен клиенту
                               │                                       │
                          Deal: Invoice Sent                      Клиент платит
                               │                                       │
                               │◄──────────────────────────────── Ops подтверждает
                               │
                          Deal: In Progress                       Factura в Holded ──► Gestoría
                               │
                          Deal: Won
```

---

### 6.2 Автоматическая отправка DocuSign envelope

#### Триггер

При изменении статуса **CRM Deal** на `Contract Sent` — Frappe автоматически отправляет DocuSign envelope.

#### Предусловия (валидация)

Перед отправкой проверить, что на Deal заполнены:
- `service_type` — обязательно
- `preferred_language` — обязательно (EN или ES)
- Contact email (через связанный Contact) — обязательно

Если хотя бы одно не заполнено — запретить переход в `Contract Sent`, показать ошибку.

#### Изменения в `hooks.py`

```python
# hooks.py — добавить:
doc_events = {
    "CRM Deal": {
        "validate": "frappe_docusign.api.crm_deal_hooks.on_deal_status_change"
    }
}
```

#### Новый файл `frappe_docusign/api/crm_deal_hooks.py`

```python
"""
Hooks for CRM Deal status changes.
Triggers DocuSign envelope when deal moves to 'Contract Sent'.

Uses `validate` (not `on_change`) so that if DocuSign API fails,
the status change is rolled back and the deal stays in its previous state.
"""
import frappe


def on_deal_status_change(doc, method=None):
    """Called on validate of CRM Deal. Checks if status changed to 'Contract Sent'."""
    
    # Only fire when status transitions TO 'Contract Sent'
    if doc.status != "Contract Sent":
        return
    
    # On new document (Convert to Deal), status is 'New' — skip
    prev = doc.get_doc_before_save()
    if not prev:
        return
    if prev.status == "Contract Sent":
        return  # No actual transition, skip

    # Validate required fields
    missing = []
    if not getattr(doc, "service_type", None):
        missing.append("service_type")
    if not getattr(doc, "preferred_language", None):
        missing.append("preferred_language")
    
    # Get signer email from linked Contact
    signer_email = _get_deal_contact_email(doc)
    if not signer_email:
        missing.append("contact email (link a Contact with email to this Deal)")
    
    if missing:
        frappe.throw(
            f"Cannot send contract: fill in {', '.join(missing)} first.",
            frappe.ValidationError,
        )

    # Get signer name from linked Contact
    signer_name = _get_deal_contact_name(doc)

    # Send DocuSign envelope
    try:
        envelope_id = _send_docusign_envelope(doc, signer_email, signer_name)
        doc.docusign_envelope_id = envelope_id
        frappe.msgprint(f"DocuSign envelope sent: {envelope_id}", alert=True)
    except Exception as e:
        frappe.log_error(f"DocuSign send failed for {doc.name}: {e}")
        frappe.throw(
            f"Failed to send DocuSign envelope: {e}. Status not changed.",
            frappe.ValidationError,
        )


def _get_deal_contact_email(doc) -> str | None:
    """Get email from the Contact linked to this Deal."""
    # CRM Deal has a `contacts` child table or a `contact` link field
    # Exact field name depends on Frappe CRM version — verify via bench console:
    #   frappe.get_meta("CRM Deal").get_field("contacts")
    # 
    # Option A: if Deal has a linked Contact field
    if doc.get("contact"):
        return frappe.db.get_value("Contact", doc.contact, "email_id")
    
    # Option B: if Deal has a contacts child table  
    if doc.get("contacts") and len(doc.contacts) > 0:
        contact_name = doc.contacts[0].contact
        return frappe.db.get_value("Contact", contact_name, "email_id")
    
    return None


def _get_deal_contact_name(doc) -> str:
    """Get full name from the Contact linked to this Deal."""
    if doc.get("contact"):
        c = frappe.get_doc("Contact", doc.contact)
        return f"{c.first_name or ''} {c.last_name or ''}".strip()
    if doc.get("contacts") and len(doc.contacts) > 0:
        c = frappe.get_doc("Contact", doc.contacts[0].contact)
        return f"{c.first_name or ''} {c.last_name or ''}".strip()
    return ""


def _send_docusign_envelope(doc, signer_email: str, signer_name: str) -> str:
    """
    Send a DocuSign envelope with two documents:
      1. Service contract (template based on service_type + preferred_language)
      2. GDPR consent (universal template, based on preferred_language)
    
    Returns: envelope_id (str)
    
    TODO: Implement using DocuSign eSignature API.
    Template IDs should be stored in DocuSign Settings or a config doctype.
    
    Pseudocode:
        settings = frappe.get_single("DocuSign Settings")
        
        contract_template_id = get_contract_template(
            doc.service_type, 
            doc.preferred_language
        )
        gdpr_template_id = get_gdpr_template(doc.preferred_language)
        
        envelope = create_envelope(
            email_subject="ArtBot — Please sign your service agreement",
            template_ids=[contract_template_id, gdpr_template_id],
            signer_email=signer_email,
            signer_name=signer_name,
        )
        
        return envelope.envelope_id
    """
    # PLACEHOLDER — replace with actual DocuSign API integration
    frappe.throw(
        "DocuSign envelope sending not yet implemented. "
        "See TODO in _send_docusign_envelope."
    )
```

---

### 6.3 DocuSign webhook → Contract Signed

#### Endpoint

Новый файл `frappe_docusign/api/docusign_webhook.py`:

```python
"""
DocuSign Connect webhook receiver.
Updates CRM Deal status when envelope is completed (all documents signed).

Endpoint: POST /api/method/frappe_docusign.api.docusign_webhook.handle
Must be registered in DocuSign Connect settings as the webhook URL.
"""
import frappe
import json


@frappe.whitelist(allow_guest=True, methods=["POST"])
def handle():
    """
    Receive DocuSign Connect webhook notification.
    
    DocuSign sends JSON payload when envelope status changes.
    We only care about status = "completed" (all signers done).
    """
    payload = frappe.request.get_data(as_text=True)
    
    # TODO: Verify HMAC signature from DocuSign Connect
    # See: https://developers.docusign.com/platform/webhooks/connect/hmac/
    # secret = frappe.get_single("DocuSign Settings").webhook_secret
    # _verify_hmac(payload, secret)
    
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        # NOTE: не используем frappe.throw() — webhook вызывается DocuSign (guest),
        # throw вернёт HTML-страницу ошибки вместо JSON и вызовет бесконечные ретраи.
        frappe.log_error("DocuSign webhook: invalid JSON payload")
        frappe.response.http_status_code = 400
        return {"status": "error", "reason": "invalid_json"}
    
    envelope_status = data.get("status") or data.get("Status")
    envelope_id = data.get("envelopeId") or data.get("EnvelopeId")
    
    if not envelope_id:
        frappe.log_error("DocuSign webhook: no envelopeId in payload")
        return {"status": "ignored", "reason": "no envelope_id"}
    
    if envelope_status != "completed":
        return {"status": "ignored", "reason": f"status={envelope_status}"}
    
    # Find CRM Deal by docusign_envelope_id
    deal_name = frappe.db.get_value(
        "CRM Deal", 
        {"docusign_envelope_id": envelope_id}, 
        "name"
    )
    
    if not deal_name:
        frappe.log_error(f"DocuSign webhook: no CRM Deal found for envelope {envelope_id}")
        return {"status": "error", "reason": "deal_not_found"}
    
    # Update status to Contract Signed
    deal = frappe.get_doc("CRM Deal", deal_name)
    if deal.status == "Contract Sent":
        deal.status = "Contract Signed"
        deal.save(ignore_permissions=True)
        # NOTE: не вызываем frappe.db.commit() — Frappe коммитит автоматически.
        return {"status": "ok", "deal": deal_name, "new_status": "Contract Signed"}
    else:
        return {
            "status": "ignored", 
            "reason": f"deal status is {deal.status}, not Contract Sent"
        }
```

#### Настройка в DocuSign

1. DocuSign Admin → Settings → Connect → Add Configuration
2. URL: `https://crm.yourdomain.com/api/method/frappe_docusign.api.docusign_webhook.handle`
3. Trigger events: `Envelope Completed`
4. Data format: JSON
5. Include: Envelope ID, Envelope Status
6. HMAC: включить, secret сохранить в DocuSign Settings в Frappe

---

### 6.4 Ручной шаг: Holded invoice

После автоматического перехода Deal в `Contract Signed`, ops-менеджер вручную:

1. Открывает Holded → Sales → New Invoice
2. Создаёт контакт (если ещё нет) — **используя тот же email, что и Contact в Frappe CRM**
3. Выставляет invoice с описанием услуги и суммой
4. Включает Stripe payment link
5. Отправляет клиенту
6. Возвращается в Frappe CRM → переводит Deal в `Invoice Sent`
7. После получения оплаты (проверяет в Holded/Stripe) → переводит Deal в `In Progress`

**Критично:** email клиента в Holded и Frappe CRM Contact должен совпадать. Это единственный идентификатор для сопоставления данных между системами.

---

### 6.5 DocuSign: структура шаблонов

| Шаблон | Язык | Документ | Примечание |
|--------|------|----------|------------|
| `contract-universal-en` | EN | Договор на оказание услуг | Пока один шаблон на все услуги |
| `contract-universal-es` | ES | Contrato de prestación de servicios | Испаноязычная версия |
| `gdpr-consent-en` | EN | GDPR / Data Processing Consent | Универсальный |
| `gdpr-consent-es` | ES | Consentimiento de tratamiento de datos | Испаноязычная версия |

**Итого на старте: 4 шаблона** (2 языка × 2 документа).

---

## Часть 7: Полный end-to-end поток

```
     WEBSITE                 FRAPPE CRM                    DOCUSIGN              HOLDED + STRIPE         GESTORÍA
     ───────                 ──────────                    ────────              ───────────────         ────────

  Регистрация
  (email/Google)
       │
       │  POST create_lead
       ▼
                       ┌─ CRM LEAD ─┐
                       │ New         │
                       │ Contacted   │
                       │ Qualified   │
                       └──────┬──────┘
                              │
                       «Convert to Deal»
                       (Contact + Org created)
                              │
                       ┌─ CRM DEAL ──────────────────────────────────────────────────────────────┐
                       │                                                                          │
                       │  New                                                                     │
                       │       │                                                                  │
                       │  Ops fills service_type,                                                 │
                       │  preferred_language                                                      │
                       │       │                                                                  │
                       │  Contract Sent ──── validate hook ───►  Envelope sent                    │
                       │       │             envelope_id saved    (contract + GDPR)               │
                       │       │                                         │                        │
                       │       │                                    Client signs both              │
                       │       │                                         │                        │
                       │  Contract Signed ◄── webhook ──────────── completed                      │
                       │       │                                                                  │
                       │  Invoice Sent ─── ops creates invoice ──────────────►  Holded invoice    │
                       │       │            in Holded manually                  + Stripe link      │
                       │       │                                                    │             │
                       │  In Progress ◄──── ops confirms ◄────────────────── Client pays          │
                       │       │                                              Factura ──► Gestoría│
                       │       │                                                                  │
                       │  Won                                                                     │
                       └──────────────────────────────────────────────────────────────────────────┘
```

---

## Часть 8: Чеклист после деплоя (полный flow)

### Lead Statuses (Frappe CRM)

- [ ] Проверить наличие дефолтных: New, Contacted, Nurture, Qualified, Unqualified, Junk
- [ ] Если отсутствуют — создать через Desk → CRM Lead Status

### Deal Statuses (Frappe CRM)

- [ ] Удалить ненужные дефолтные: Qualification, Demo/Making, Proposal/Quotation, Negotiation, Ready to Close
- [ ] Создать кастомные: New (gray), Contract Sent (orange), Contract Signed (blue), Invoice Sent (yellow), In Progress (purple)
- [ ] Проверить что Won (green), Lost (red) на месте
- [ ] Проверить порядок: New → Contract Sent → Contract Signed → Invoice Sent → In Progress → Won → Lost

### Кастомные поля на CRM Deal

- [ ] `service_type` (Select: Immigration, Tax Consulting, Sworn Translation, Insurance)
- [ ] `preferred_language` (Select: EN, ES)
- [ ] `docusign_envelope_id` (Data, read-only)

### DocuSign

- [ ] Создать 4 шаблона: contract-universal-en, contract-universal-es, gdpr-consent-en, gdpr-consent-es
- [ ] Содержание шаблонов согласовано с юристом
- [ ] Template ID сохранены в Frappe
- [ ] Connect webhook настроен → URL на Frappe endpoint
- [ ] HMAC secret сохранён в Frappe
- [ ] Тестовый envelope отправлен и подписан → Deal статус обновился

### Frappe (DocuSign интеграция)

- [ ] `hooks.py` обновлён: добавлен `doc_events` для **CRM Deal** (не Lead!)
- [ ] Файл `crm_deal_hooks.py` создан и задеплоен
- [ ] Файл `docusign_webhook.py` создан и задеплоен
- [ ] `_send_docusign_envelope()` реализован (заменён placeholder)
- [ ] Проверен переход Contract Sent → envelope отправлен → Contract Signed (webhook)
- [ ] Проверена валидация: переход без заполненных полей → ошибка

### Holded

- [ ] Stripe подключён к Holded
- [ ] Создан тестовый invoice с payment link
- [ ] Gestoría имеет доступ к данным

---

## Часть 9: Открытые вопросы

### Из v1

1. **Поля CRM Lead** — названия могут отличаться (`email` vs `email_id`). Проверить через bench console.
2. **Допустимые значения `source`** — проверить и обновить `_map_source()`.
3. **`isNewUser` в NextAuth** — работает только с database adapter.
4. **UTM в отдельных полях** — в будущем добавить кастомные поля вместо `notes`.

### Из v2

5. **Шаблоны договоров и GDPR** — кто готовит тексты? Юрист?
6. **Тариф DocuSign** — сколько envelopes в месяц?
7. **Один документ или два** — GDPR как приложение к договору?
8. **Prepay vs postpay** — текущий flow предполагает prepay.
9. **Gestoría: доступ к Holded** — напрямую или через выгрузку?
10. **Прайс-лист услуг** — фиксированный или индивидуальный?
11. **HMAC-верификация webhook** — реализовать до продакшена.

### Из v2.1

12. **Contact link на Deal** — точное имя поля (`contact`, `contacts` child table, или другое). Проверить через `frappe.get_meta("CRM Deal")` перед реализацией.
13. **Email на Contact** — точное имя поля (`email_id`, `email`, или другое). Проверить.

---

## Часть 10: Будущие итерации (не в scope)

- **Stripe webhook → Frappe:** автоматический `Invoice Sent` → `In Progress`
- **Frappe → Holded API:** автоматическое создание invoice при `Contract Signed`
- **Раздельные шаблоны договоров** по `service_type`
- **Client Portal** на сайте ArtBot
- **Verifactu / SII** интеграция в Holded
- **UTM-поля** как кастомные поля на CRM Lead
- **Automated reminders:** напоминание если envelope не подписан за X дней
- **Повторные Deal:** один клиент (Contact) → несколько Deal (Immigration, потом Tax Consulting)
