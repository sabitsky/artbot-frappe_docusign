app_name = "frappe_docusign"
app_title = "Frappe DocuSign"
app_publisher = "ArtBot"
app_description = "DocuSign eSignature integration for Frappe CRM"
app_email = ""
app_license = "MIT"
app_version = "0.1.0"

after_install = "frappe_docusign.install.after_install"

# Runs after every `bench migrate` — keeps the CRM Form Script in sync
# with the JS file in the repository after a git pull.
after_migrate = ["frappe_docusign.install.after_migrate"]

# Frappe Desk fallback: loads the same JS when CRM Deal is opened via /app/crm-deal
# In Frappe CRM (Vue UI), the script is loaded via the CRM Form Script record
# created by after_install / after_migrate.
doctype_js = {
    "CRM Deal": "public/js/crm_deal_docusign.js",
}

# Automatically triggers DocuSign envelope when CRM Deal status → "Contract Sent".
# Uses validate hook so a failed send rolls back the status change.
doc_events = {
    "CRM Deal": {
        "validate": "frappe_docusign.api.crm_deal_hooks.on_deal_status_change",
    }
}

# Export custom fields on CRM Deal so they are applied automatically
# when the app is installed on any new site.
fixtures = [
    # DocuSign tracking fields (docusign_section, docusign_envelope_id, etc.)
    {
        "dt": "Custom Field",
        "filters": [["name", "like", "CRM Deal-docusign_%"]],
    },
    # Service fields used to determine DocuSign template and language
    {
        "dt": "Custom Field",
        "filters": [["name", "in", ["CRM Deal-service_type", "CRM Deal-preferred_language"]]],
    },
]
