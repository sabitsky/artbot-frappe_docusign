import frappe
from frappe.model.document import Document


class DocuSignSettings(Document):
    def validate(self):
        if self.enabled:
            self._validate_required_fields()
        if self.environment == "Sandbox":
            self._set_sandbox_defaults()
        elif self.environment == "Production":
            self._set_production_defaults()

    def _validate_required_fields(self):
        required = [
            ("integration_key", "Integration Key"),
            ("account_id", "Account ID"),
            ("user_id", "User ID"),
            ("base_url", "Base URL"),
            ("auth_server", "Auth Server"),
        ]
        missing = [label for field, label in required if not self.get(field)]
        if missing:
            frappe.throw(
                f"The following fields are required to enable DocuSign: {', '.join(missing)}",
                frappe.MandatoryError,
            )

    def _set_sandbox_defaults(self):
        if not self.base_url:
            self.base_url = "https://demo.docusign.net/restapi"
        if not self.auth_server:
            self.auth_server = "https://account-d.docusign.com"

    def _set_production_defaults(self):
        if not self.base_url:
            self.base_url = "https://na4.docusign.net/restapi"
        if not self.auth_server:
            self.auth_server = "https://account.docusign.com"
