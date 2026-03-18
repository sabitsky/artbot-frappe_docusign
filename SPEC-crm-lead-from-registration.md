# Spec: Создание CRM Lead при регистрации пользователя на сайте

**Версия:** 1.0
**Дата:** 2026-03-18
**Статус:** Ready for implementation

---

## Контекст

Когда пользователь регистрируется на сайте (Next.js) через email или Google — в Frappe CRM автоматически создаётся лид в статусе `New`. Если лид с таким email уже существует — дубль не создаётся, возвращается ID существующего.

**Стек:**
- Backend CRM: Frappe (self-hosted), приложение `frappe_docusign`
- Frontend/сайт: Next.js (App Router)
- Auth на сайте: NextAuth.js или Supabase Auth

---

## Что нужно реализовать

1. **Frappe:** новый файл `frappe_docusign/api/crm_lead.py` — whitelisted endpoint
2. **Frappe:** тесты `frappe_docusign/api/tests/test_crm_lead.py`
3. **Next.js:** API Route `app/api/crm/register-lead/route.ts` — server-side прокси
4. **Next.js:** вызов из auth callback при регистрации нового пользователя
5. **Next.js:** middleware для сбора UTM-параметров в cookie
6. **Frappe:** создать служебного пользователя + API Key (инструкция ниже)

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
    frappe.db.commit()

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

**Никаких изменений в `hooks.py` не требуется** — `@frappe.whitelist` достаточно для регистрации endpoint.

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

### 1.4 Создание служебного пользователя в Frappe

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

### 1.5 Ручная проверка endpoint через curl

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
        signal: AbortSignal.timeout(5000),
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
      const utm = getUtmFromCookie()  // читаем из cookie (см. 2.5)

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
export function getUtmFromCookie(): UtmData {
  const cookieStore = cookies()
  const raw = cookieStore.get(UTM_COOKIE)?.value
  if (!raw) return {}
  try {
    return JSON.parse(raw) as UtmData
  } catch {
    return {}
  }
}
```

Сохранять UTM в cookie при первом визите — в middleware или в корневом layout:

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

## Часть 3: Полный поток данных

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
         ├─ lead.insert() + frappe.db.commit()
         └─ return {lead: "CRM-LEAD-0002", created: true}
         │
         ▼
registerLeadInCRM возвращает result | null
Ошибка CRM НЕ блокирует auth flow пользователя
```

---

## Часть 4: Чеклист после деплоя

### Frappe (выполнить на сервере)

- [ ] Убедиться что файл `frappe_docusign/api/crm_lead.py` попал в репозиторий и задеплоен
- [ ] `bench --site {site} migrate` (на всякий случай)
- [ ] Проверить поля CRM Lead через bench console (см. 1.2)
- [ ] Если `source` значения не совпадают — обновить `_map_source()` в `crm_lead.py`
- [ ] Создать пользователя `website-integration@internal` и сгенерировать API Keys
- [ ] Выдать пользователю права на создание CRM Lead
- [ ] Проверить endpoint через curl (см. 1.5)
- [ ] Запустить тесты: `bench --site {site} run-tests --app frappe_docusign --module frappe_docusign.api.tests.test_crm_lead`

### Next.js

- [ ] Добавить ENV: `FRAPPE_URL`, `FRAPPE_API_KEY`, `FRAPPE_API_SECRET`
- [ ] Создать `lib/crm.ts` (см. 2.2)
- [ ] Создать `lib/utm.ts` (см. 2.5)
- [ ] Обновить `middleware.ts` для сохранения UTM в cookie (см. 2.5)
- [ ] Добавить вызов `registerLeadInCRM` в auth callback (см. 2.3)
- [ ] Проверить в логах: при регистрации нового пользователя — лог `[CRM]` должен отсутствовать (нет ошибок) или содержать `created: true`
- [ ] Зарегистрировать тестового пользователя → проверить в Frappe CRM что лид появился
- [ ] Зарегистрировать с тем же email снова → убедиться что дубль НЕ создался

---

## Часть 5: Что НЕ менять

- `hooks.py` — не нужны изменения
- `install.py` — не нужны изменения
- Существующие тесты — не трогать
- DocuSign Settings DocType — не трогать

---

## Открытые вопросы (уточнить при реализации)

1. **Поля CRM Lead** — названия полей могут отличаться (`email` vs `email_id`, `notes` vs `note`). Проверить через bench console перед деплоем.
2. **Допустимые значения `source`** — Frappe CRM может иметь фиксированный Select-список. Проверить и обновить `_map_source()`.
3. **`isNewUser` в NextAuth** — работает только с database adapter. Если используется JWT-only стратегия — нужна альтернативная логика (флаг при создании в БД).
4. **UTM в отдельных полях** — если в будущем понадобятся кастомные поля `utm_source`, `utm_medium`, `utm_campaign` на CRM Lead — добавить через `Customize Form` в Frappe и обновить endpoint.
