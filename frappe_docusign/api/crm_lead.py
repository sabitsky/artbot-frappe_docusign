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
