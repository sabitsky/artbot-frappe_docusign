"""
Hooks for CRM Deal status changes.
Triggers DocuSign envelope when deal moves to 'Contract Sent'.

Uses `validate` (not `on_change`) so that if DocuSign API fails,
the status change is rolled back and the deal stays in its previous state.

NOTE: The webhook for receiving DocuSign completion events is handled by
frappe_docusign.api.webhook (handle_docusign_event) — which includes full
HMAC-SHA256 verification and dual-format (Legacy + SIM) payload parsing.
Register that endpoint in DocuSign Connect, not a separate webhook file.
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
    """
    Get email from the Contact linked to this Deal.

    NOTE: Exact field name depends on Frappe CRM version — verify via bench console:
        frappe.get_meta("CRM Deal").get_field("contacts")
    See Open Question #12 in the spec.
    """
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

    TODO: Implement using DocuSign eSignature API with templates.
    Template IDs should be stored in DocuSign Settings or a dedicated config doctype.

    Pseudocode:
        settings = frappe.get_single("DocuSign Settings")

        contract_template_id = _get_contract_template(
            doc.service_type,
            doc.preferred_language
        )
        gdpr_template_id = _get_gdpr_template(doc.preferred_language)

        envelope = create_envelope_from_templates(
            email_subject="ArtBot — Please sign your service agreement",
            template_ids=[contract_template_id, gdpr_template_id],
            signer_email=signer_email,
            signer_name=signer_name,
        )

        return envelope.envelope_id

    Until templates are created in DocuSign, raise to block status change.
    """
    # PLACEHOLDER — replace with actual DocuSign API integration
    frappe.throw(
        "DocuSign envelope sending not yet implemented. "
        "See TODO in frappe_docusign/api/crm_deal_hooks.py → _send_docusign_envelope(). "
        "Required: DocuSign templates for contract + GDPR in EN/ES.",
        frappe.ValidationError,
    )
