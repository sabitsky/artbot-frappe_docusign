// lib/crm.ts
// Server-side only — never import from client components.
// Copy this file into your Next.js project at lib/crm.ts

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
        // AbortSignal.timeout() доступен с Node.js 17.3+
        // Fallback для более ранних версий
        signal: AbortSignal.timeout?.(5000) ?? (() => {
          const ctrl = new AbortController()
          setTimeout(() => ctrl.abort(), 5000)
          return ctrl.signal
        })(),
      }
    )

    if (!res.ok) {
      const text = await res.text()
      console.error(`[CRM] Frappe returned ${res.status}: ${text}`)
      return null
    }

    // Frappe оборачивает ответ @whitelist функций в { message: ... }
    const data = await res.json()
    return data.message as RegisterLeadResult
  } catch (err) {
    console.error("[CRM] Failed to register lead:", err)
    return null
  }
}
