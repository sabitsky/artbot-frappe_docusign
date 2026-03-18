"""
Tests for frappe_docusign.api.crm_lead.create_lead

Run:
    bench --site {site} run-tests --app frappe_docusign \
        --module frappe_docusign.api.tests.test_crm_lead
"""
import frappe
from frappe.tests.utils import FrappeTestCase

from frappe_docusign.api.crm_lead import create_lead, _map_source

_TEST_EMAIL = "crm_lead_test_user@example.com"


class TestCreateLead(FrappeTestCase):

    def tearDown(self):
        # Clean up any leads created during tests
        leads = frappe.get_all("CRM Lead", filters={"email": _TEST_EMAIL}, pluck="name")
        for name in leads:
            frappe.delete_doc("CRM Lead", name, force=True)
        frappe.db.commit()

    # ------------------------------------------------------------------
    # Happy path
    # ------------------------------------------------------------------

    def test_creates_lead_and_returns_created_true(self):
        result = create_lead(
            email=_TEST_EMAIL,
            first_name="Ivan",
            last_name="Petrov",
            source="email",
        )
        self.assertTrue(result["created"])
        self.assertTrue(frappe.db.exists("CRM Lead", result["lead"]))

    def test_lead_has_correct_email(self):
        result = create_lead(email=_TEST_EMAIL)
        doc = frappe.get_doc("CRM Lead", result["lead"])
        self.assertEqual(doc.email, _TEST_EMAIL)

    def test_lead_status_is_new(self):
        result = create_lead(email=_TEST_EMAIL)
        doc = frappe.get_doc("CRM Lead", result["lead"])
        self.assertEqual(doc.status, "New")

    def test_lead_name_uses_full_name_when_provided(self):
        result = create_lead(email=_TEST_EMAIL, first_name="Ivan", last_name="Petrov")
        doc = frappe.get_doc("CRM Lead", result["lead"])
        self.assertEqual(doc.lead_name, "Ivan Petrov")

    def test_lead_name_falls_back_to_email_when_no_name(self):
        result = create_lead(email=_TEST_EMAIL)
        doc = frappe.get_doc("CRM Lead", result["lead"])
        self.assertEqual(doc.lead_name, _TEST_EMAIL)

    def test_utm_stored_in_notes(self):
        result = create_lead(
            email=_TEST_EMAIL,
            utm_source="google",
            utm_medium="cpc",
            utm_campaign="spring2026",
        )
        doc = frappe.get_doc("CRM Lead", result["lead"])
        self.assertIn("utm_source=google", doc.notes)
        self.assertIn("utm_medium=cpc", doc.notes)
        self.assertIn("utm_campaign=spring2026", doc.notes)

    def test_no_notes_when_no_utm(self):
        result = create_lead(email=_TEST_EMAIL)
        doc = frappe.get_doc("CRM Lead", result["lead"])
        self.assertFalse(doc.notes)

    # ------------------------------------------------------------------
    # Deduplication
    # ------------------------------------------------------------------

    def test_duplicate_email_returns_existing_lead(self):
        r1 = create_lead(email=_TEST_EMAIL, first_name="Ivan")
        r2 = create_lead(email=_TEST_EMAIL, first_name="Ivan2")
        self.assertEqual(r1["lead"], r2["lead"])
        self.assertFalse(r2["created"])

    def test_dedup_is_case_insensitive(self):
        r1 = create_lead(email=_TEST_EMAIL.lower())
        r2 = create_lead(email=_TEST_EMAIL.upper())
        self.assertEqual(r1["lead"], r2["lead"])
        self.assertFalse(r2["created"])

    def test_only_one_lead_exists_after_duplicate_call(self):
        create_lead(email=_TEST_EMAIL)
        create_lead(email=_TEST_EMAIL)
        count = frappe.db.count("CRM Lead", {"email": _TEST_EMAIL})
        self.assertEqual(count, 1)

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def test_empty_email_raises_validation_error(self):
        with self.assertRaises(frappe.ValidationError):
            create_lead(email="")

    def test_whitespace_only_email_raises_validation_error(self):
        with self.assertRaises(frappe.ValidationError):
            create_lead(email="   ")

    # ------------------------------------------------------------------
    # Source mapping
    # ------------------------------------------------------------------

    def test_google_source_maps_to_social_media(self):
        self.assertEqual(_map_source("google"), "Social Media")

    def test_email_source_maps_to_website(self):
        self.assertEqual(_map_source("email"), "Website")

    def test_unknown_source_maps_to_website(self):
        self.assertEqual(_map_source("unknown_provider"), "Website")

    def test_empty_source_maps_to_website(self):
        self.assertEqual(_map_source(""), "Website")

    def test_source_mapping_is_case_insensitive(self):
        self.assertEqual(_map_source("GOOGLE"), "Social Media")
