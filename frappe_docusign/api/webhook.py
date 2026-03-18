"""
DocuSign Connect webhook handler.

Webhook URL to configure in DocuSign Connect:
    https://{your-domain}/api/method/frappe_docusign.api.webhook.handle_docusign_event

Supports both DocuSign Connect payload formats:
  - Legacy (Classic): top-level envelopeId + status in Title Case
  - SIM (Connect 2.0): top-level "event" key + data.envelopeSummary.status in lowercase

HMAC verification uses X-DocuSign-Signature-1 header (HMAC-SHA256, base64-encoded).
The webhook always returns HTTP 200 to prevent DocuSign retries; errors go to Error Log.
"""
import base64
import hashlib
import hmac as _hmac
import json

import frappe

from frappe_docusign.api.utils import update_deal_stage


@frappe.whitelist(allow_guest=True)
def handle_docusign_event():
    """
    Entry point for DocuSign Connect webhook POST requests.

    Flow:
      1. Verify HMAC signature (if webhook_secret is configured)
      2. Parse payload — detect Legacy vs SIM format
      3. Look up CRM Deal by docusign_envelope_id
      4. Dispatch to _on_completed / _on_declined based on status
    """
    payload_bytes = frappe.request.data
    settings = frappe.get_single("DocuSign Settings")
    secret = settings.get_password("webhook_secret")

    if secret:
        sig = frappe.request.headers.get("X-DocuSign-Signature-1", "")
        if not verify_hmac(payload_bytes, sig, secret):
            frappe.log_error(
                f"HMAC verification failed. Signature header: {sig[:40]}",
                "frappe_docusign: Webhook Security",
            )
            frappe.response.http_status_code = 401
            return {"error": "Invalid signature"}

    try:
        data = json.loads(payload_bytes)
    except json.JSONDecodeError as exc:
        frappe.log_error(
            f"Could not parse webhook JSON: {exc}",
            "frappe_docusign: Webhook Parse Error",
        )
        frappe.response.http_status_code = 200
        return "ok"

    envelope_id, status = _parse_webhook_payload(data)

    if not envelope_id:
        frappe.log_error(
            f"Could not extract envelope_id from webhook. Top-level keys: {list(data.keys())}",
            "frappe_docusign: Webhook Parse Error",
        )
        frappe.response.http_status_code = 200
        return "ok"

    deals = frappe.get_all(
        "CRM Deal",
        filters={"docusign_envelope_id": envelope_id},
        fields=["name", "deal_owner", "docusign_status"],
        limit=1,
    )

    if not deals:
        frappe.log_error(
            f"Webhook for envelope {envelope_id} — no matching CRM Deal found.",
            "frappe_docusign: Webhook Warning",
        )
        frappe.response.http_status_code = 200
        return "ok"

    deal_name = deals[0]["name"]
    deal_owner = deals[0].get("deal_owner")

    if status == "completed":
        _on_completed(deal_name)
    elif status == "declined":
        _on_declined(deal_name, deal_owner)
    elif status == "voided":
        frappe.db.set_value("CRM Deal", deal_name, "docusign_status", "Voided")
        frappe.db.commit()

    frappe.response.http_status_code = 200
    return "ok"


# ---------------------------------------------------------------------------
# HMAC verification
# ---------------------------------------------------------------------------

def verify_hmac(payload_bytes: bytes, signature_header: str, secret: str) -> bool:
    """
    Verify the X-DocuSign-Signature-1 header.

    DocuSign computes: base64(HMAC-SHA256(secret, raw_body))
    Returns True if the computed value matches the header.
    """
    if not signature_header or not secret:
        return False

    computed = base64.b64encode(
        _hmac.new(
            secret.encode("utf-8"),
            payload_bytes,
            hashlib.sha256,
        ).digest()
    ).decode("utf-8")

    return _hmac.compare_digest(computed, signature_header)


# ---------------------------------------------------------------------------
# Payload parsing (dual-format)
# ---------------------------------------------------------------------------

def _parse_webhook_payload(data: dict):
    """
    Extract (envelope_id, status_lowercase) from a DocuSign Connect payload.

    Handles:
      - SIM format (Connect 2.0): has top-level "event" key;
            envelope_id at data["data"]["envelopeId"]
            status at data["data"]["envelopeSummary"]["status"] (already lowercase)
      - Legacy format: envelope_id at data["envelopeId"], status at data["status"] (Title Case)

    Returns (None, None) if parsing fails.
    """
    if "event" in data:
        # SIM / Connect 2.0 format
        try:
            envelope_id = data["data"]["envelopeId"]
            status = data["data"]["envelopeSummary"]["status"].lower()
            return envelope_id, status
        except (KeyError, AttributeError, TypeError):
            return None, None

    # Legacy format
    envelope_id = data.get("envelopeId")
    raw_status = data.get("status", "")
    status = raw_status.lower() if raw_status else ""
    return envelope_id, status


# ---------------------------------------------------------------------------
# Event handlers
# ---------------------------------------------------------------------------

def _on_completed(deal_name: str) -> None:
    """Envelope completed: update status, set completed_at, advance stage."""
    # Idempotency: skip if already marked Completed
    current = frappe.db.get_value("CRM Deal", deal_name, "docusign_status")
    if current == "Completed":
        return

    from frappe.utils import now_datetime

    frappe.db.set_value(
        "CRM Deal",
        deal_name,
        {
            "docusign_status": "Completed",
            "docusign_completed_at": now_datetime(),
            "docusign_error": "",
        },
    )
    update_deal_stage(deal_name, "Contract Signed")
    frappe.db.commit()


def _on_declined(deal_name: str, deal_owner) -> None:
    """Envelope declined: update status and notify the deal owner by email."""
    frappe.db.set_value("CRM Deal", deal_name, "docusign_status", "Declined")
    frappe.db.commit()

    if deal_owner:
        _notify_owner_declined(deal_name, deal_owner)


def _notify_owner_declined(deal_name: str, deal_owner: str) -> None:
    try:
        owner_email = frappe.db.get_value("User", deal_owner, "email")
        if not owner_email:
            return
        frappe.sendmail(
            recipients=[owner_email],
            subject=f"DocuSign: signing declined — deal {deal_name}",
            message=(
                f"<p>The client has <strong>declined</strong> to sign the documents "
                f"for deal <strong>{deal_name}</strong>.</p>"
                f"<p>Please review the deal and follow up with the client.</p>"
            ),
        )
    except Exception as exc:
        frappe.log_error(
            f"Could not send declined notification for deal {deal_name}: {exc}",
            "frappe_docusign: Email Error",
        )
