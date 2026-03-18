"""
Install and migrate hooks for frappe_docusign.

after_install  — runs once on `bench install-app`
after_migrate  — runs on every `bench migrate` (keeps CRM Form Script up to date)
"""
import os

import frappe

# ---------------------------------------------------------------------------
# ArtBot Deal Status pipeline (Frappe CRM v2 uses CRM Deal Status, not CRM Stage)
#
# These statuses are created automatically on install.
# Frappe CRM defaults (Qualification, Demo/Making, Proposal/Quotation,
# Negotiation, Ready to Close) must be deleted MANUALLY via the UI after
# install — see ADMIN_INSTALL_GUIDE.md § "Deal Statuses".
# Won and Lost (Frappe CRM defaults) are kept as-is.
# ---------------------------------------------------------------------------
OUR_DEAL_STATUSES = [
    # position 1-5: our pipeline (inserted before Won/Lost which sit at 6-7)
    {"deal_status": "New",              "type": "Open",    "probability": 10,  "color": "gray",   "position": 1},
    {"deal_status": "Contract Sent",    "type": "Ongoing", "probability": 50,  "color": "orange", "position": 2},
    {"deal_status": "Contract Signed",  "type": "Ongoing", "probability": 80,  "color": "blue",   "position": 3},
    {"deal_status": "Invoice Sent",     "type": "Ongoing", "probability": 90,  "color": "yellow", "position": 4},
    {"deal_status": "In Progress",      "type": "Ongoing", "probability": 95,  "color": "purple", "position": 5},
    # Won (pos 6) and Lost (pos 7) already exist as Frappe CRM defaults — skip.
]

_FORM_SCRIPT_NAME = "DocuSign Buttons - CRM Deal"
_JS_FILE = os.path.join(os.path.dirname(__file__), "public/js/crm_deal_docusign.js")


def after_install():
    if not frappe.db.exists("DocType", "CRM Deal Status"):
        frappe.log_error(
            "Frappe CRM is not installed or CRM Deal Status DocType is missing. "
            "Deal statuses were NOT created. Install Frappe CRM v2 first, "
            "then create them manually via https://{site}/app/crm-deal-status",
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
    Create ArtBot pipeline statuses. Skips any that already exist.
    Sets explicit positions 1-5 so our statuses appear before Won/Lost (6-7).

    After install, the admin must manually DELETE the Frappe CRM defaults:
        Qualification, Demo/Making, Proposal/Quotation, Negotiation, Ready to Close
    See ADMIN_INSTALL_GUIDE.md for step-by-step instructions.
    """
    created, skipped = [], []

    for entry in OUR_DEAL_STATUSES:
        status_name = entry["deal_status"]
        if frappe.db.exists("CRM Deal Status", {"deal_status": status_name}):
            skipped.append(status_name)
            continue
        try:
            doc = frappe.new_doc("CRM Deal Status")
            doc.deal_status = status_name
            doc.type = entry["type"]
            doc.probability = entry["probability"]
            doc.color = entry["color"]
            doc.position = entry["position"]
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
