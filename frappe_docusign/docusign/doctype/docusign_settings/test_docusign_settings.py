"""
TDD tests for DocuSign Settings DocType.

Run:
    bench --site {site} run-tests --app frappe_docusign \
        --module frappe_docusign.docusign.doctype.docusign_settings.test_docusign_settings
"""
import frappe
from frappe.tests.utils import FrappeTestCase


class TestDocuSignSettings(FrappeTestCase):
    def _reset_settings(self):
        """Return settings to a known neutral state before each test."""
        settings = frappe.get_single("DocuSign Settings")
        settings.enabled = 0
        settings.integration_key = ""
        settings.account_id = ""
        settings.user_id = ""
        settings.base_url = ""
        settings.auth_server = ""
        settings.environment = "Sandbox"
        settings.save(ignore_permissions=True)
        frappe.db.commit()

    def setUp(self):
        self._reset_settings()

    def tearDown(self):
        self._reset_settings()

    # --- DocType structure ---

    def test_settings_is_single_doctype(self):
        meta = frappe.get_meta("DocuSign Settings")
        self.assertTrue(meta.issingle)

    def test_settings_has_required_fields(self):
        meta = frappe.get_meta("DocuSign Settings")
        fieldnames = {f.fieldname for f in meta.fields}
        expected = {
            "enabled", "environment", "integration_key", "account_id",
            "user_id", "base_url", "auth_server", "private_key", "webhook_secret",
        }
        self.assertTrue(
            expected.issubset(fieldnames),
            f"Missing fields: {expected - fieldnames}",
        )

    # --- Validation: disabled settings ---

    def test_disabled_settings_do_not_require_api_fields(self):
        settings = frappe.get_single("DocuSign Settings")
        settings.enabled = 0
        settings.integration_key = ""
        settings.account_id = ""
        settings.save(ignore_permissions=True)  # must not raise

    # --- Validation: enabled settings ---

    def test_enabled_settings_raise_if_integration_key_missing(self):
        settings = frappe.get_single("DocuSign Settings")
        settings.enabled = 1
        settings.integration_key = ""
        settings.account_id = "acc-id"
        settings.user_id = "user-id"
        settings.base_url = "https://demo.docusign.net/restapi"
        settings.auth_server = "https://account-d.docusign.com"
        with self.assertRaises(frappe.MandatoryError):
            settings.save(ignore_permissions=True)

    def test_enabled_settings_raise_if_account_id_missing(self):
        settings = frappe.get_single("DocuSign Settings")
        settings.enabled = 1
        settings.integration_key = "key"
        settings.account_id = ""
        settings.user_id = "user-id"
        settings.base_url = "https://demo.docusign.net/restapi"
        settings.auth_server = "https://account-d.docusign.com"
        with self.assertRaises(frappe.MandatoryError):
            settings.save(ignore_permissions=True)

    def test_enabled_settings_with_all_fields_saves_successfully(self):
        settings = frappe.get_single("DocuSign Settings")
        settings.enabled = 1
        settings.integration_key = "key"
        settings.account_id = "acc"
        settings.user_id = "user"
        settings.base_url = "https://demo.docusign.net/restapi"
        settings.auth_server = "https://account-d.docusign.com"
        settings.environment = "Sandbox"
        settings.save(ignore_permissions=True)  # must not raise

    # --- Auto-fill URLs ---

    def test_sandbox_environment_fills_empty_base_url(self):
        settings = frappe.get_single("DocuSign Settings")
        settings.environment = "Sandbox"
        settings.base_url = ""
        settings.auth_server = ""
        settings.save(ignore_permissions=True)
        settings.reload()
        self.assertEqual(settings.base_url, "https://demo.docusign.net/restapi")
        self.assertEqual(settings.auth_server, "https://account-d.docusign.com")

    def test_production_environment_fills_empty_base_url(self):
        settings = frappe.get_single("DocuSign Settings")
        settings.environment = "Production"
        settings.base_url = ""
        settings.auth_server = ""
        settings.save(ignore_permissions=True)
        settings.reload()
        self.assertEqual(settings.base_url, "https://na4.docusign.net/restapi")
        self.assertEqual(settings.auth_server, "https://account.docusign.com")

    def test_existing_urls_are_not_overridden_by_defaults(self):
        settings = frappe.get_single("DocuSign Settings")
        settings.environment = "Sandbox"
        settings.base_url = "https://custom.docusign.net/restapi"
        settings.auth_server = "https://custom-auth.docusign.com"
        settings.save(ignore_permissions=True)
        settings.reload()
        self.assertEqual(settings.base_url, "https://custom.docusign.net/restapi")
        self.assertEqual(settings.auth_server, "https://custom-auth.docusign.com")
