"""
Diagnostic endpoint — Iteration 2 only.

Used by the server admin to identify the correct CRM Deal field names
(stage, contact email, contact name) before the Client Script is written in Iteration 3.

Usage — run on the server after installing the app:
    curl -s -X GET \
      "https://{site}/api/method/frappe_docusign.api.diagnostic.get_crm_deal_fields" \
      -H "Authorization: token {api_key}:{api_secret}"

Or from bench console:
    bench --site {site} execute frappe_docusign.api.diagnostic.get_crm_deal_fields

Remove this file after Iteration 3 field names are confirmed.
"""
import frappe


@frappe.whitelist()
def get_crm_deal_fields():
    """
    Return all CRM Deal fields with their fieldname, fieldtype, label, and options.

    Look for:
      - The stage field (likely 'pipeline_stage' or 'stage', type Link to CRM Stage)
      - The email field (likely 'email' or 'contact_email', type Data/Email)
      - The contact name field (likely 'lead_name' or 'contact_name', type Data)

    Report results back so the Client Script in Iteration 3 uses the correct names.
    """
    meta = frappe.get_meta("CRM Deal")
    skip_types = {"Section Break", "Column Break", "HTML", "Fold", "Heading", "Tab Break"}

    fields = [
        {
            "fieldname": f.fieldname,
            "fieldtype": f.fieldtype,
            "label": f.label,
            "options": f.options,
            "reqd": bool(f.reqd),
        }
        for f in meta.fields
        if f.fieldtype not in skip_types
    ]

    # Highlight likely candidates for stage / email / name
    stage_candidates = [f for f in fields if "stage" in f["fieldname"]]
    email_candidates = [f for f in fields if "email" in f["fieldname"]]
    name_candidates = [
        f for f in fields
        if any(k in f["fieldname"] for k in ("name", "contact", "lead", "customer"))
        and f["fieldtype"] == "Data"
    ]

    return {
        "all_fields": fields,
        "stage_candidates": stage_candidates,
        "email_candidates": email_candidates,
        "name_candidates": name_candidates,
        "note": (
            "Use stage_candidates, email_candidates, name_candidates to identify "
            "the correct fieldnames for the CRM Form Script in Iteration 3."
        ),
    }
