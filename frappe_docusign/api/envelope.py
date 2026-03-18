"""
DocuSign envelope operations.

send_envelope  — creates and sends an envelope via DocuSign eSign REST API v2.1.
check_status   — fetches current envelope status from DocuSign and syncs the CRM Deal.

Whitelisted endpoints:
    /api/method/frappe_docusign.api.envelope.send_envelope
    /api/method/frappe_docusign.api.envelope.check_status
"""
import base64
import json
import os

import frappe
import requests
from frappe.utils import get_site_path, now_datetime

from frappe_docusign.api.utils import update_deal_stage


@frappe.whitelist()
def send_envelope(deal, documents, signer_name, signer_email):
    """
    Create and send a DocuSign envelope for a CRM Deal.

    Args:
        deal         : CRM Deal name (document identifier)
        documents    : JSON-encoded list of Frappe file URLs, e.g. ["/files/contract.pdf"]
        signer_name  : Recipient's full name
        signer_email : Recipient's email address

    Side-effects on the CRM Deal (on success):
        docusign_envelope_id  ← DocuSign envelope GUID
        docusign_status       ← "Sent"
        docusign_sent_at      ← current datetime
        docusign_link         ← DocuSign envelope viewer URL
        docusign_error        ← cleared
        pipeline_stage/stage  ← "Contract Sent"
    """
    settings = frappe.get_single("DocuSign Settings")
    if not settings.enabled:
        frappe.throw(
            "DocuSign integration is disabled. Enable it in DocuSign Settings.",
            frappe.ValidationError,
        )

    deal_doc = frappe.get_doc("CRM Deal", deal)
    if deal_doc.get("docusign_envelope_id"):
        frappe.throw(
            f"This deal already has DocuSign envelope {deal_doc.docusign_envelope_id}. "
            "Use 'Check Status' to refresh, or contact support to void the existing envelope.",
            frappe.ValidationError,
        )

    if isinstance(documents, str):
        documents = json.loads(documents)
    if not documents:
        frappe.throw("At least one document is required.", frappe.ValidationError)

    try:
        payload = _build_envelope_payload(documents, signer_name, signer_email)
        url = f"{settings.base_url}/v2.1/accounts/{settings.account_id}/envelopes"
        resp = _call_docusign(requests.post, url, json=payload)

        if not resp.ok:
            _store_error_and_throw(deal, resp)

        envelope_id = resp.json()["envelopeId"]

        frappe.db.set_value(
            "CRM Deal",
            deal,
            {
                "docusign_envelope_id": envelope_id,
                "docusign_status": "Sent",
                "docusign_sent_at": now_datetime(),
                "docusign_link": _envelope_viewer_url(envelope_id),
                "docusign_error": "",
            },
        )
        update_deal_stage(deal, "Contract Sent")
        frappe.db.commit()

        return {"envelope_id": envelope_id, "status": "Sent"}

    except frappe.ValidationError:
        raise
    except Exception as exc:
        frappe.db.set_value("CRM Deal", deal, "docusign_error", str(exc)[:500])
        frappe.db.commit()
        raise


@frappe.whitelist()
def check_status(deal):
    """
    Fetch current DocuSign envelope status and sync it to the CRM Deal.

    Returns the current status string (e.g. "Sent", "Completed", "Declined").
    """
    deal_doc = frappe.get_doc("CRM Deal", deal)
    envelope_id = deal_doc.get("docusign_envelope_id")

    if not envelope_id:
        frappe.throw(
            "This deal has no DocuSign envelope. Use 'Send for Signing' first.",
            frappe.ValidationError,
        )

    settings = frappe.get_single("DocuSign Settings")
    url = (
        f"{settings.base_url}/v2.1/accounts/{settings.account_id}"
        f"/envelopes/{envelope_id}"
    )
    resp = _call_docusign(requests.get, url)

    if not resp.ok:
        _store_error_and_throw(deal, resp)

    data = resp.json()
    # DocuSign GET /envelopes/{id} returns status in Title Case
    status = data.get("status", "").capitalize()

    updates = {"docusign_status": status, "docusign_error": ""}
    if status == "Completed":
        updates["docusign_completed_at"] = now_datetime()

    frappe.db.set_value("CRM Deal", deal, updates)

    if status == "Completed":
        update_deal_stage(deal, "Contract Signed")

    frappe.db.commit()
    return status


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _build_envelope_payload(documents: list, signer_name: str, signer_email: str) -> dict:
    docs = []
    for i, file_url in enumerate(documents, start=1):
        raw = _read_file_bytes(file_url)
        filename = file_url.rstrip("/").split("/")[-1]
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "pdf"
        docs.append(
            {
                "documentBase64": base64.b64encode(raw).decode(),
                "name": filename,
                "fileExtension": ext,
                "documentId": str(i),
            }
        )

    return {
        "emailSubject": "Please sign your documents — ArtBot",
        "documents": docs,
        "recipients": {
            "signers": [
                {
                    "email": signer_email,
                    "name": signer_name,
                    "recipientId": "1",
                    "routingOrder": "1",
                    "tabs": {
                        "signHereTabs": [
                            {
                                "anchorString": "/sig1/",
                                "anchorUnits": "pixels",
                                "anchorXOffset": "0",
                                "anchorYOffset": "0",
                            }
                        ]
                    },
                }
            ]
        },
        "status": "sent",
    }


def _read_file_bytes(file_url: str) -> bytes:
    """Read a Frappe-managed file from disk and return raw bytes."""
    if file_url.startswith("/private"):
        path = os.path.join(get_site_path(), file_url.lstrip("/"))
    else:
        path = os.path.join(get_site_path("public"), file_url.lstrip("/"))

    if not os.path.exists(path):
        frappe.throw(f"File not found on server: {file_url}", frappe.ValidationError)

    with open(path, "rb") as fh:
        return fh.read()


def _call_docusign(http_method, url, **kwargs):
    """
    Make an authenticated DocuSign API call.
    On 401, clears the token cache and retries once.
    """
    from frappe_docusign.api.auth import get_access_token, invalidate_token_cache

    def _headers(token):
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    resp = http_method(url, headers=_headers(get_access_token()), timeout=30, **kwargs)

    if resp.status_code == 401:
        invalidate_token_cache()
        resp = http_method(url, headers=_headers(get_access_token()), timeout=30, **kwargs)

    return resp


def _envelope_viewer_url(envelope_id: str) -> str:
    settings = frappe.get_single("DocuSign Settings")
    base = (
        "https://appdemo.docusign.com"
        if settings.environment == "Sandbox"
        else "https://app.docusign.com"
    )
    return f"{base}/documents/details/{envelope_id}"


def _store_error_and_throw(deal: str, resp) -> None:
    msg = f"DocuSign error {resp.status_code}: {resp.text[:400]}"
    frappe.db.set_value("CRM Deal", deal, "docusign_error", msg)
    frappe.db.commit()
    frappe.throw(msg, frappe.ValidationError)
