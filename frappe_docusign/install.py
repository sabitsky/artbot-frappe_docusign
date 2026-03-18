"""
Install and migrate hooks for frappe_docusign.

after_install  — runs once on `bench install-app`
after_migrate  — runs on every `bench migrate` (keeps CRM Form Script up to date)
"""
import os

import frappe

# Full pipeline expected by the DocuSign integration.
# Stages that already exist in the CRM are skipped safely.
PIPELINE_STAGES = [
    "Lead",
    "Qualified",
    "Proposal Sent",
    "Contract Sent",
    "Contract Signed",
    "Onboarding",
]

_FORM_SCRIPT_NAME = "DocuSign Buttons - CRM Deal"
_JS_FILE = os.path.join(os.path.dirname(__file__), "public/js/crm_deal_docusign.js")


def after_install():
    if not frappe.db.exists("DocType", "CRM Stage"):
        frappe.log_error(
            "Frappe CRM is not installed or CRM Stage DocType is missing. "
            "Pipeline stages were NOT created. Install Frappe CRM first, "
            "then manually create: " + ", ".join(PIPELINE_STAGES),
            "frappe_docusign: Install Warning",
        )
    else:
        _create_crm_stages()

    _upsert_crm_form_script()


def after_migrate():
    """
    Keeps the CRM Form Script in sync with the JS file in the repository.
    Runs automatically on every `bench migrate` after a git pull.
    """
    _upsert_crm_form_script()


# ---------------------------------------------------------------------------
# CRM pipeline stages
# ---------------------------------------------------------------------------

def _create_crm_stages():
    created, skipped = [], []

    for stage_name in PIPELINE_STAGES:
        if frappe.db.exists("CRM Stage", stage_name):
            skipped.append(stage_name)
            continue
        try:
            doc = frappe.new_doc("CRM Stage")
            doc.name = stage_name
            doc.insert(ignore_permissions=True, ignore_if_duplicate=True)
            created.append(stage_name)
        except Exception as exc:
            frappe.log_error(
                f"Could not create CRM Stage '{stage_name}': {exc}. "
                "Please create this stage manually via CRM settings.",
                "frappe_docusign: Install Warning",
            )

    frappe.db.commit()

    if created:
        print(f"frappe_docusign: Created CRM stages: {', '.join(created)}")
    if skipped:
        print(f"frappe_docusign: Skipped existing CRM stages: {', '.join(skipped)}")


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
