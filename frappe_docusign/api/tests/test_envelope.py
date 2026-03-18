"""
TDD tests for frappe_docusign.api.envelope

Tests are written BEFORE the implementation is considered final.
All external DocuSign HTTP calls and file-system reads are mocked.

Run:
    bench --site {site} run-tests --app frappe_docusign \
        --module frappe_docusign.api.tests.test_envelope
"""
import json
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

def _make_mock_ds_response(status_code=200, json_body=None, text=""):
    resp = MagicMock()
    resp.status_code = status_code
    resp.ok = status_code < 400
    resp.json.return_value = json_body or {}
    resp.text = text
    return resp


def _make_deal(**kwargs):
    """Create a minimal CRM Deal for testing; ignores mandatory validation."""
    doc = frappe.new_doc("CRM Deal")
    doc.flags.ignore_mandatory = True
    for k, v in kwargs.items():
        setattr(doc, k, v)
    doc.insert(ignore_permissions=True)
    return doc


# ---------------------------------------------------------------------------
# TestSendEnvelope
# ---------------------------------------------------------------------------

class TestSendEnvelope(FrappeTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Enable DocuSign Settings for all envelope tests
        s = frappe.get_single("DocuSign Settings")
        s.enabled = 1
        s.integration_key = "key"
        s.account_id = "acc-id"
        s.user_id = "user-id"
        s.base_url = "https://demo.docusign.net/restapi"
        s.auth_server = "https://account-d.docusign.com"
        s.environment = "Sandbox"
        s.save(ignore_permissions=True)
        frappe.db.commit()

    def setUp(self):
        # Fresh deal for every test; FrappeTestCase rolls back after each test
        self.deal = _make_deal(lead_name="Test Client")
        self.deal_name = self.deal.name

    # --- guard rails ---

    def test_raises_if_docusign_disabled(self):
        s = frappe.get_single("DocuSign Settings")
        s.enabled = 0
        s.save(ignore_permissions=True)
        try:
            from frappe_docusign.api.envelope import send_envelope
            with self.assertRaises(frappe.ValidationError):
                send_envelope(
                    deal=self.deal_name,
                    documents=json.dumps(["/files/a.pdf"]),
                    signer_name="Client",
                    signer_email="c@test.com",
                )
        finally:
            s.enabled = 1
            s.save(ignore_permissions=True)

    def test_raises_if_envelope_already_exists(self):
        frappe.db.set_value(
            "CRM Deal", self.deal_name, "docusign_envelope_id", "existing-id"
        )
        from frappe_docusign.api.envelope import send_envelope
        with self.assertRaises(frappe.ValidationError):
            send_envelope(
                deal=self.deal_name,
                documents=json.dumps(["/files/a.pdf"]),
                signer_name="Client",
                signer_email="c@test.com",
            )

    def test_raises_if_documents_list_is_empty(self):
        from frappe_docusign.api.envelope import send_envelope
        with self.assertRaises(frappe.ValidationError):
            send_envelope(
                deal=self.deal_name,
                documents=json.dumps([]),
                signer_name="Client",
                signer_email="c@test.com",
            )

    # --- happy path ---

    @patch("frappe_docusign.api.envelope._call_docusign")
    @patch("frappe_docusign.api.envelope._read_file_bytes")
    def test_happy_path_sets_envelope_id_on_deal(self, mock_read, mock_call):
        mock_read.return_value = b"%PDF-1.4 fake"
        mock_call.return_value = _make_mock_ds_response(
            200, {"envelopeId": "env-abc-123"}
        )

        from frappe_docusign.api.envelope import send_envelope
        result = send_envelope(
            deal=self.deal_name,
            documents=json.dumps(["/files/contract.pdf"]),
            signer_name="Jane Doe",
            signer_email="jane@example.com",
        )

        self.assertEqual(result["envelope_id"], "env-abc-123")
        self.assertEqual(result["status"], "Sent")

        envelope_id = frappe.db.get_value(
            "CRM Deal", self.deal_name, "docusign_envelope_id"
        )
        self.assertEqual(envelope_id, "env-abc-123")

    @patch("frappe_docusign.api.envelope._call_docusign")
    @patch("frappe_docusign.api.envelope._read_file_bytes")
    def test_happy_path_sets_status_sent(self, mock_read, mock_call):
        mock_read.return_value = b"%PDF-1.4 fake"
        mock_call.return_value = _make_mock_ds_response(200, {"envelopeId": "env-1"})

        from frappe_docusign.api.envelope import send_envelope
        send_envelope(
            deal=self.deal_name,
            documents=json.dumps(["/files/a.pdf"]),
            signer_name="A",
            signer_email="a@b.com",
        )

        status = frappe.db.get_value("CRM Deal", self.deal_name, "docusign_status")
        self.assertEqual(status, "Sent")

    @patch("frappe_docusign.api.envelope._call_docusign")
    @patch("frappe_docusign.api.envelope._read_file_bytes")
    def test_happy_path_sets_sent_at(self, mock_read, mock_call):
        mock_read.return_value = b"%PDF-1.4 fake"
        mock_call.return_value = _make_mock_ds_response(200, {"envelopeId": "env-2"})

        from frappe_docusign.api.envelope import send_envelope
        send_envelope(
            deal=self.deal_name,
            documents=json.dumps(["/files/a.pdf"]),
            signer_name="A",
            signer_email="a@b.com",
        )

        sent_at = frappe.db.get_value("CRM Deal", self.deal_name, "docusign_sent_at")
        self.assertIsNotNone(sent_at)

    @patch("frappe_docusign.api.envelope._call_docusign")
    @patch("frappe_docusign.api.envelope._read_file_bytes")
    def test_happy_path_clears_error_field(self, mock_read, mock_call):
        frappe.db.set_value("CRM Deal", self.deal_name, "docusign_error", "old error")
        mock_read.return_value = b"%PDF-1.4 fake"
        mock_call.return_value = _make_mock_ds_response(200, {"envelopeId": "env-3"})

        from frappe_docusign.api.envelope import send_envelope
        send_envelope(
            deal=self.deal_name,
            documents=json.dumps(["/files/a.pdf"]),
            signer_name="A",
            signer_email="a@b.com",
        )

        error = frappe.db.get_value("CRM Deal", self.deal_name, "docusign_error")
        self.assertEqual(error or "", "")

    # --- DocuSign viewer link ---

    @patch("frappe_docusign.api.envelope._call_docusign")
    @patch("frappe_docusign.api.envelope._read_file_bytes")
    def test_sandbox_link_uses_appdemo_domain(self, mock_read, mock_call):
        mock_read.return_value = b"%PDF fake"
        mock_call.return_value = _make_mock_ds_response(
            200, {"envelopeId": "env-sandbox"}
        )
        frappe.db.set_value(
            "DocuSign Settings", "DocuSign Settings", "environment", "Sandbox"
        )

        from frappe_docusign.api.envelope import send_envelope
        send_envelope(
            deal=self.deal_name,
            documents=json.dumps(["/files/a.pdf"]),
            signer_name="A",
            signer_email="a@b.com",
        )

        link = frappe.db.get_value("CRM Deal", self.deal_name, "docusign_link")
        self.assertIn("appdemo.docusign.com", link)
        self.assertIn("env-sandbox", link)

    @patch("frappe_docusign.api.envelope._call_docusign")
    @patch("frappe_docusign.api.envelope._read_file_bytes")
    def test_production_link_uses_app_domain(self, mock_read, mock_call):
        mock_read.return_value = b"%PDF fake"
        mock_call.return_value = _make_mock_ds_response(
            200, {"envelopeId": "env-prod"}
        )
        frappe.db.set_value(
            "DocuSign Settings", "DocuSign Settings", "environment", "Production"
        )

        try:
            from frappe_docusign.api.envelope import send_envelope
            send_envelope(
                deal=self.deal_name,
                documents=json.dumps(["/files/a.pdf"]),
                signer_name="A",
                signer_email="a@b.com",
            )
            link = frappe.db.get_value("CRM Deal", self.deal_name, "docusign_link")
            self.assertIn("app.docusign.com", link)
            self.assertNotIn("appdemo", link)
        finally:
            frappe.db.set_value(
                "DocuSign Settings", "DocuSign Settings", "environment", "Sandbox"
            )

    # --- DocuSign API errors ---

    @patch("frappe_docusign.api.envelope._call_docusign")
    @patch("frappe_docusign.api.envelope._read_file_bytes")
    def test_docusign_400_stores_error_on_deal(self, mock_read, mock_call):
        mock_read.return_value = b"%PDF fake"
        mock_call.return_value = _make_mock_ds_response(
            400, text="Bad request - invalid document"
        )

        from frappe_docusign.api.envelope import send_envelope
        with self.assertRaises(frappe.ValidationError):
            send_envelope(
                deal=self.deal_name,
                documents=json.dumps(["/files/a.pdf"]),
                signer_name="A",
                signer_email="a@b.com",
            )

        error = frappe.db.get_value("CRM Deal", self.deal_name, "docusign_error")
        self.assertIn("400", error)

    @patch("frappe_docusign.api.envelope._call_docusign")
    @patch("frappe_docusign.api.envelope._read_file_bytes")
    def test_docusign_400_does_not_change_deal_stage(self, mock_read, mock_call):
        mock_read.return_value = b"%PDF fake"
        mock_call.return_value = _make_mock_ds_response(400, text="Bad request")

        from frappe_docusign.api.envelope import send_envelope
        try:
            send_envelope(
                deal=self.deal_name,
                documents=json.dumps(["/files/a.pdf"]),
                signer_name="A",
                signer_email="a@b.com",
            )
        except frappe.ValidationError:
            pass

        envelope_id = frappe.db.get_value(
            "CRM Deal", self.deal_name, "docusign_envelope_id"
        )
        self.assertFalsy(envelope_id)

    # --- 401 retry logic ---

    @patch("frappe_docusign.api.envelope._read_file_bytes")
    def test_docusign_401_retries_with_fresh_token(self, mock_read):
        mock_read.return_value = b"%PDF fake"

        call_count = {"n": 0}

        def side_effect(method, url, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return _make_mock_ds_response(401, text="Unauthorized")
            return _make_mock_ds_response(200, {"envelopeId": "env-retry-ok"})

        with patch("frappe_docusign.api.envelope._call_docusign", side_effect=side_effect):
            # _call_docusign itself handles the retry internally; here we verify
            # that after a 401 the function eventually succeeds when the second
            # call returns 200.
            # We patch at the requests level to exercise the actual retry in _call_docusign.
            pass

        # Direct test of _call_docusign retry behaviour
        with patch("frappe_docusign.api.auth.get_access_token", return_value="tok"), \
             patch("frappe_docusign.api.auth.invalidate_token_cache"), \
             patch("requests.post") as mock_post:

            mock_post.side_effect = [
                _make_mock_ds_response(401, text="Unauthorized"),
                _make_mock_ds_response(200, {"envelopeId": "env-after-retry"}),
            ]

            from frappe_docusign.api.envelope import _call_docusign
            resp = _call_docusign(mock_post, "https://example.com/envelopes", json={})

            self.assertEqual(mock_post.call_count, 2)
            self.assertTrue(resp.ok)


# ---------------------------------------------------------------------------
# TestCheckStatus
# ---------------------------------------------------------------------------

class TestCheckStatus(FrappeTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        s = frappe.get_single("DocuSign Settings")
        s.enabled = 1
        s.base_url = "https://demo.docusign.net/restapi"
        s.account_id = "acc-id"
        s.environment = "Sandbox"
        s.save(ignore_permissions=True)
        frappe.db.commit()

    def setUp(self):
        self.deal = _make_deal(lead_name="Status Test Client")
        self.deal_name = self.deal.name
        frappe.db.set_value(
            "CRM Deal", self.deal_name, "docusign_envelope_id", "test-envelope-xyz"
        )

    def test_raises_if_no_envelope_id(self):
        frappe.db.set_value(
            "CRM Deal", self.deal_name, "docusign_envelope_id", ""
        )
        from frappe_docusign.api.envelope import check_status
        with self.assertRaises(frappe.ValidationError):
            check_status(deal=self.deal_name)

    @patch("frappe_docusign.api.envelope._call_docusign")
    def test_updates_docusign_status_field(self, mock_call):
        mock_call.return_value = _make_mock_ds_response(
            200, {"status": "Delivered"}
        )
        from frappe_docusign.api.envelope import check_status
        result = check_status(deal=self.deal_name)

        self.assertEqual(result, "Delivered")
        status = frappe.db.get_value("CRM Deal", self.deal_name, "docusign_status")
        self.assertEqual(status, "Delivered")

    @patch("frappe_docusign.api.envelope._call_docusign")
    def test_completed_status_sets_completed_at(self, mock_call):
        mock_call.return_value = _make_mock_ds_response(
            200, {"status": "Completed"}
        )
        from frappe_docusign.api.envelope import check_status
        check_status(deal=self.deal_name)

        completed_at = frappe.db.get_value(
            "CRM Deal", self.deal_name, "docusign_completed_at"
        )
        self.assertIsNotNone(completed_at)

    @patch("frappe_docusign.api.envelope._call_docusign")
    def test_completed_status_clears_error_field(self, mock_call):
        frappe.db.set_value("CRM Deal", self.deal_name, "docusign_error", "old error")
        mock_call.return_value = _make_mock_ds_response(
            200, {"status": "Completed"}
        )
        from frappe_docusign.api.envelope import check_status
        check_status(deal=self.deal_name)

        error = frappe.db.get_value("CRM Deal", self.deal_name, "docusign_error")
        self.assertEqual(error or "", "")

    @patch("frappe_docusign.api.envelope._call_docusign")
    def test_api_error_stores_error_and_throws(self, mock_call):
        mock_call.return_value = _make_mock_ds_response(
            404, text="Envelope not found"
        )
        from frappe_docusign.api.envelope import check_status
        with self.assertRaises(frappe.ValidationError):
            check_status(deal=self.deal_name)

        error = frappe.db.get_value("CRM Deal", self.deal_name, "docusign_error")
        self.assertIn("404", error)

    # --- _build_envelope_payload unit tests ---

    def test_build_payload_base64_encodes_document(self):
        from frappe_docusign.api.envelope import _build_envelope_payload
        import base64

        fake_bytes = b"%PDF-1.4 content here"
        with patch("frappe_docusign.api.envelope._read_file_bytes", return_value=fake_bytes):
            payload = _build_envelope_payload(
                ["/files/doc.pdf"], "Signer Name", "signer@example.com"
            )

        doc = payload["documents"][0]
        decoded = base64.b64decode(doc["documentBase64"])
        self.assertEqual(decoded, fake_bytes)

    def test_build_payload_extracts_filename_and_extension(self):
        from frappe_docusign.api.envelope import _build_envelope_payload

        with patch("frappe_docusign.api.envelope._read_file_bytes", return_value=b"x"):
            payload = _build_envelope_payload(
                ["/files/my_contract.pdf"], "A", "a@b.com"
            )

        doc = payload["documents"][0]
        self.assertEqual(doc["name"], "my_contract.pdf")
        self.assertEqual(doc["fileExtension"], "pdf")

    def test_build_payload_assigns_sequential_document_ids(self):
        from frappe_docusign.api.envelope import _build_envelope_payload

        with patch("frappe_docusign.api.envelope._read_file_bytes", return_value=b"x"):
            payload = _build_envelope_payload(
                ["/files/a.pdf", "/files/b.pdf"], "A", "a@b.com"
            )

        self.assertEqual(payload["documents"][0]["documentId"], "1")
        self.assertEqual(payload["documents"][1]["documentId"], "2")

    def test_build_payload_sets_status_sent(self):
        from frappe_docusign.api.envelope import _build_envelope_payload

        with patch("frappe_docusign.api.envelope._read_file_bytes", return_value=b"x"):
            payload = _build_envelope_payload(["/files/a.pdf"], "A", "a@b.com")

        self.assertEqual(payload["status"], "sent")

    def test_build_payload_includes_sign_here_anchor(self):
        from frappe_docusign.api.envelope import _build_envelope_payload

        with patch("frappe_docusign.api.envelope._read_file_bytes", return_value=b"x"):
            payload = _build_envelope_payload(["/files/a.pdf"], "A", "a@b.com")

        tabs = payload["recipients"]["signers"][0]["tabs"]
        anchors = [t["anchorString"] for t in tabs["signHereTabs"]]
        self.assertIn("/sig1/", anchors)

    # --- _envelope_viewer_url unit tests ---

    def test_viewer_url_sandbox(self):
        frappe.db.set_value(
            "DocuSign Settings", "DocuSign Settings", "environment", "Sandbox"
        )
        from frappe_docusign.api.envelope import _envelope_viewer_url
        url = _envelope_viewer_url("abc-123")
        self.assertIn("appdemo.docusign.com", url)
        self.assertIn("abc-123", url)

    def test_viewer_url_production(self):
        frappe.db.set_value(
            "DocuSign Settings", "DocuSign Settings", "environment", "Production"
        )
        try:
            from frappe_docusign.api.envelope import _envelope_viewer_url
            url = _envelope_viewer_url("abc-123")
            self.assertIn("app.docusign.com", url)
            self.assertNotIn("appdemo", url)
        finally:
            frappe.db.set_value(
                "DocuSign Settings", "DocuSign Settings", "environment", "Sandbox"
            )

    def assertFalsy(self, value, msg=None):
        if value:
            raise AssertionError(msg or f"Expected falsy value, got {value!r}")
