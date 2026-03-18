"""
Install and migrate hooks for frappe_docusign.

after_install  — runs once on `bench install-app`
after_migrate  — runs on every `bench migrate` (keeps CRM Form Script up to date)
"""
import os

import frappe

# Frappe CRM v2 uses CRM Deal Status (not CRM Stage).
# Default statuses (Qualification, Demo/Making, Proposal/Quotation, etc.)
# are created by Frappe CRM itself. We only add the two statuses that our
# DocuSign integration sets and that do not exist in the CRM defaults.
OUR_DEAL_STATUSES = [
    {"deal_status": "Contract Sent",   "type": "Ongoing", "probability": 80},
    {"deal_status": "Contract Signed", "type": "Won",     "probability": 95},
]

_FORM_SCRIPT_NAME = "DocuSign Buttons - CRM Deal"
_JS_FILE = os.path.join(os.path.dirname(__file__), "public/js/crm_deal_docusign.js")


def after_install():
    if not frappe.db.exists("DocType", "CRM Deal Status"):
        frappe.log_error(
            "Frappe CRM is not installed or CRM Deal Status DocType is missing. "
            "DocuSign statuses (Contract Sent, Contract Signed) were NOT created. "
            "Install Frappe CRM v2 first, then create them manually via "
            "/app/crm-deal-status",
            "frappe_docusign: Install Warning",
        )
    else:
        _create_crm_deal_statuses()

    _upsert_crm_form_script()


def after_migrate():
    """
    Keeps the CRM Form Script in sync with the JS file in the repository.
    Runs automatically on every `bench migrate` after a git pull.
    """
    _upsert_crm_form_script()


# ---------------------------------------------------------------------------
# CRM Deal Statuses (Frappe CRM v2)
# ---------------------------------------------------------------------------

def _create_crm_deal_statuses():
    """
    Create the two CRM Deal Status records used by the DocuSign integration.
    Frappe CRM's own installer already creates the default statuses
    (Qualification, Demo/Making, Proposal/Quotation, etc.).
    We only add Contract Sent and Contract Signed.
    """
    created, skipped = [], []

    # Find the highest existing position so we append after the defaults.
    max_pos = frappe.db.sql(
        "SELECT COALESCE(MAX(position), 5) FROM `tabCRM Deal Status`"
    )[0][0]

    for i, entry in enumerate(OUR_DEAL_STATUSES, start=1):
        status_name = entry["deal_status"]
        if frappe.db.exists("CRM Deal Status", {"deal_status": status_name}):
            skipped.append(status_name)
            continue
        try:
            doc = frappe.new_doc("CRM Deal Status")
            doc.deal_status = status_name
            doc.type = entry["type"]
            doc.probability = entry["probability"]
            doc.position = max_pos + i
            doc.insert(ignore_permissions=True, ignore_if_duplicate=True)
            created.append(status_name)
        except Exception as exc:
            frappe.log_error(
                f"Could not create CRM Deal Status '{status_name}': {exc}. "
                "Please create it manually via /app/crm-deal-status",
                "frappe_docusign: Install Warning",
            )

    frappe.db.commit()

    if created:
        print(f"frappe_docusign: Created CRM Deal Statuses: {', '.join(created)}")
    if skipped:
        print(f"frappe_docusign: Skipped existing CRM Deal Statuses: {', '.join(skipped)}")


# ---------------------------------------------------------------------------
# CRM Form Script (Frappe CRM Vue UI buttons)
# ---------------------------------------------------------------------------

def _upsert_crm_form_script():
    """
    Create or update the CRM Form Script that adds DocuSign buttons to the
    CRM Deal form in the Frappe CRM Vue UI.

    Runs on install and on every migrate so the script stays current with
    the version in public/js/crm_deal_docusign.js.
    """
    if not frappe.db.exists("DocType", "CRM Form Script"):
        frappe.log_error(
            "CRM Form Script DocType not found. "
            "Frappe CRM may not be installed. "
            "The DocuSign buttons will NOT appear on the CRM Deal form.",
            "frappe_docusign: Install Warning",
        )
        return

    try:
        with open(_JS_FILE) as fh:
            script_content = fh.read()
    except OSError as exc:
        frappe.log_error(
            f"Could not read JS file {_JS_FILE}: {exc}",
            "frappe_docusign: Install Error",
        )
        return

    if frappe.db.exists("CRM Form Script", _FORM_SCRIPT_NAME):
        doc = frappe.get_doc("CRM Form Script", _FORM_SCRIPT_NAME)
        if doc.script == script_content:
            print("frappe_docusign: CRM Form Script is already up to date.")
            return
        doc.script = script_content
        doc.enabled = 1
        doc.save(ignore_permissions=True)
        print("frappe_docusign: CRM Form Script updated.")
    else:
        frappe.get_doc(
            {
                "doctype": "CRM Form Script",
                "name": _FORM_SCRIPT_NAME,
                "dt": "CRM Deal",
                "script": script_content,
                "enabled": 1,
            }
        ).insert(ignore_permissions=True)
        print("frappe_docusign: CRM Form Script created.")

    frappe.db.commit()
