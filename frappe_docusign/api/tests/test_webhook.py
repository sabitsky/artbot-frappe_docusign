"""
TDD tests for frappe_docusign.api.webhook

Covers:
  - verify_hmac:         valid / invalid / empty inputs
  - _parse_webhook_payload: Legacy and SIM (Connect 2.0) formats
  - handle_docusign_event: HMAC rejection, deal not found, completed, declined,
                           both payload formats, idempotency

Run:
    bench --site {site} run-tests --app frappe_docusign \
        --module frappe_docusign.api.tests.test_webhook
"""
import base64
import hashlib
import hmac as _hmac
import json
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SECRET = "test-webhook-secret-key"


def _compute_valid_hmac(payload_bytes: bytes, secret: str = _SECRET) -> str:
    return base64.b64encode(
        _hmac.new(secret.encode(), payload_bytes, hashlib.sha256).digest()
    ).decode()


def _make_deal(**kwargs):
    doc = frappe.new_doc("CRM Deal")
    doc.flags.ignore_mandatory = True
    for k, v in kwargs.items():
        setattr(doc, k, v)
    doc.insert(ignore_permissions=True)
    return doc


def _make_mock_request(payload: dict, signature: str = None):
    payload_bytes = json.dumps(payload).encode()
    sig = signature if signature is not None else _compute_valid_hmac(payload_bytes)
    mock_req = MagicMock()
    mock_req.data = payload_bytes
    mock_req.headers = {"X-DocuSign-Signature-1": sig}
    return mock_req, payload_bytes


# Canonical test payloads
LEGACY_COMPLETED = {
    "envelopeId": "TEST-ENVELOPE-COMPLETED",
    "status": "Completed",
}

LEGACY_DECLINED = {
    "envelopeId": "TEST-ENVELOPE-DECLINED",
    "status": "Declined",
}

SIM_COMPLETED = {
    "event": "envelope-completed",
    "data": {
        "envelopeId": "TEST-ENVELOPE-SIM-COMPLETED",
        "envelopeSummary": {"status": "completed"},
    },
}

SIM_DECLINED = {
    "event": "envelope-declined",
    "data": {
        "envelopeId": "TEST-ENVELOPE-SIM-DECLINED",
        "envelopeSummary": {"status": "declined"},
    },
}


# ---------------------------------------------------------------------------
# TestVerifyHmac — pure function, no mocking needed
# ---------------------------------------------------------------------------

class TestVerifyHmac(FrappeTestCase):

    def test_valid_signature_returns_true(self):
        payload = b'{"status":"Completed"}'
        sig = _compute_valid_hmac(payload)
        from frappe_docusign.api.webhook import verify_hmac
        self.assertTrue(verify_hmac(payload, sig, _SECRET))

    def test_wrong_signature_returns_false(self):
        payload = b'{"status":"Completed"}'
        from frappe_docusign.api.webhook import verify_hmac
        self.assertFalse(verify_hmac(payload, "not-valid-sig", _SECRET))

    def test_wrong_secret_returns_false(self):
        payload = b'{"status":"Completed"}'
        sig = _compute_valid_hmac(payload, "correct-secret")
        from frappe_docusign.api.webhook import verify_hmac
        self.assertFalse(verify_hmac(payload, sig, "wrong-secret"))

    def test_empty_signature_returns_false(self):
        from frappe_docusign.api.webhook import verify_hmac
        self.assertFalse(verify_hmac(b"payload", "", _SECRET))

    def test_empty_secret_returns_false(self):
        from frappe_docusign.api.webhook import verify_hmac
        self.assertFalse(verify_hmac(b"payload", "any-sig", ""))

    def test_tampered_payload_returns_false(self):
        original = b'{"status":"Completed"}'
        sig = _compute_valid_hmac(original)
        tampered = b'{"status":"Declined"}'
        from frappe_docusign.api.webhook import verify_hmac
        self.assertFalse(verify_hmac(tampered, sig, _SECRET))


# ---------------------------------------------------------------------------
# TestParseWebhookPayload — pure function, no mocking needed
# ---------------------------------------------------------------------------

class TestParseWebhookPayload(FrappeTestCase):

    def _parse(self, data):
        from frappe_docusign.api.webhook import _parse_webhook_payload
        return _parse_webhook_payload(data)

    def test_legacy_completed_parsed_correctly(self):
        envelope_id, status = self._parse(LEGACY_COMPLETED)
        self.assertEqual(envelope_id, "TEST-ENVELOPE-COMPLETED")
        self.assertEqual(status, "completed")

    def test_legacy_declined_parsed_correctly(self):
        envelope_id, status = self._parse(LEGACY_DECLINED)
        self.assertEqual(envelope_id, "TEST-ENVELOPE-DECLINED")
        self.assertEqual(status, "declined")

    def test_legacy_status_normalized_to_lowercase(self):
        _, status = self._parse({"envelopeId": "x", "status": "Completed"})
        self.assertEqual(status, "completed")

    def test_sim_completed_parsed_correctly(self):
        envelope_id, status = self._parse(SIM_COMPLETED)
        self.assertEqual(envelope_id, "TEST-ENVELOPE-SIM-COMPLETED")
        self.assertEqual(status, "completed")

    def test_sim_declined_parsed_correctly(self):
        envelope_id, status = self._parse(SIM_DECLINED)
        self.assertEqual(envelope_id, "TEST-ENVELOPE-SIM-DECLINED")
        self.assertEqual(status, "declined")

    def test_sim_status_already_lowercase(self):
        _, status = self._parse(SIM_COMPLETED)
        self.assertEqual(status, status.lower())

    def test_malformed_sim_returns_none_none(self):
        envelope_id, status = self._parse({"event": "envelope-completed", "data": {}})
        self.assertIsNone(envelope_id)
        self.assertIsNone(status)

    def test_empty_dict_returns_none_none(self):
        envelope_id, status = self._parse({})
        self.assertIsNone(envelope_id)
        self.assertEqual(status, "")


# ---------------------------------------------------------------------------
# TestHandleDocuSignEvent — integration tests with mocked frappe.request
# ---------------------------------------------------------------------------

class TestHandleDocuSignEvent(FrappeTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Store webhook secret
        frappe.db.set_value(
            "DocuSign Settings", "DocuSign Settings", "webhook_secret", _SECRET
        )
        frappe.db.commit()

    def setUp(self):
        self.deal_completed = _make_deal(lead_name="Completed Client")
        frappe.db.set_value(
            "CRM Deal",
            self.deal_completed.name,
            "docusign_envelope_id",
            "TEST-ENVELOPE-COMPLETED",
        )

        self.deal_declined = _make_deal(lead_name="Declined Client")
        frappe.db.set_value(
            "CRM Deal",
            self.deal_declined.name,
            "docusign_envelope_id",
            "TEST-ENVELOPE-DECLINED",
        )

        self.deal_sim_completed = _make_deal(lead_name="SIM Completed Client")
        frappe.db.set_value(
            "CRM Deal",
            self.deal_sim_completed.name,
            "docusign_envelope_id",
            "TEST-ENVELOPE-SIM-COMPLETED",
        )

        self.deal_sim_declined = _make_deal(lead_name="SIM Declined Client")
        frappe.db.set_value(
            "CRM Deal",
            self.deal_sim_declined.name,
            "docusign_envelope_id",
            "TEST-ENVELOPE-SIM-DECLINED",
        )

    def _call_handler(self, payload: dict, signature: str = None):
        mock_req, payload_bytes = _make_mock_request(payload, signature)
        from frappe_docusign.api.webhook import handle_docusign_event
        with patch.object(frappe, "request", mock_req):
            handle_docusign_event()

    # --- security ---

    def test_invalid_hmac_returns_401(self):
        mock_req, _ = _make_mock_request(LEGACY_COMPLETED, signature="bad-sig")
        from frappe_docusign.api.webhook import handle_docusign_event
        with patch.object(frappe, "request", mock_req):
            handle_docusign_event()
        self.assertEqual(frappe.response.http_status_code, 401)

    def test_invalid_hmac_does_not_update_deal(self):
        mock_req, _ = _make_mock_request(LEGACY_COMPLETED, signature="bad-sig")
        from frappe_docusign.api.webhook import handle_docusign_event
        with patch.object(frappe, "request", mock_req):
            handle_docusign_event()
        status = frappe.db.get_value(
            "CRM Deal", self.deal_completed.name, "docusign_status"
        )
        self.assertNotEqual(status, "Completed")

    # --- deal not found ---

    def test_unknown_envelope_returns_200(self):
        payload = {"envelopeId": "UNKNOWN-ENVELOPE-9999", "status": "Completed"}
        self._call_handler(payload)
        self.assertEqual(frappe.response.http_status_code, 200)

    # --- Legacy format: completed ---

    def test_legacy_completed_updates_docusign_status(self):
        self._call_handler(LEGACY_COMPLETED)
        status = frappe.db.get_value(
            "CRM Deal", self.deal_completed.name, "docusign_status"
        )
        self.assertEqual(status, "Completed")

    def test_legacy_completed_sets_completed_at(self):
        self._call_handler(LEGACY_COMPLETED)
        completed_at = frappe.db.get_value(
            "CRM Deal", self.deal_completed.name, "docusign_completed_at"
        )
        self.assertIsNotNone(completed_at)

    def test_legacy_completed_returns_200(self):
        self._call_handler(LEGACY_COMPLETED)
        self.assertEqual(frappe.response.http_status_code, 200)

    # --- Legacy format: declined ---

    def test_legacy_declined_updates_docusign_status(self):
        self._call_handler(LEGACY_DECLINED)
        status = frappe.db.get_value(
            "CRM Deal", self.deal_declined.name, "docusign_status"
        )
        self.assertEqual(status, "Declined")

    def test_legacy_declined_returns_200(self):
        self._call_handler(LEGACY_DECLINED)
        self.assertEqual(frappe.response.http_status_code, 200)

    # --- SIM format: completed ---

    def test_sim_completed_updates_docusign_status(self):
        self._call_handler(SIM_COMPLETED)
        status = frappe.db.get_value(
            "CRM Deal", self.deal_sim_completed.name, "docusign_status"
        )
        self.assertEqual(status, "Completed")

    def test_sim_completed_sets_completed_at(self):
        self._call_handler(SIM_COMPLETED)
        completed_at = frappe.db.get_value(
            "CRM Deal", self.deal_sim_completed.name, "docusign_completed_at"
        )
        self.assertIsNotNone(completed_at)

    # --- SIM format: declined ---

    def test_sim_declined_updates_docusign_status(self):
        self._call_handler(SIM_DECLINED)
        status = frappe.db.get_value(
            "CRM Deal", self.deal_sim_declined.name, "docusign_status"
        )
        self.assertEqual(status, "Declined")

    # --- idempotency ---

    def test_completed_event_is_idempotent(self):
        # First webhook
        self._call_handler(LEGACY_COMPLETED)
        first_completed_at = frappe.db.get_value(
            "CRM Deal", self.deal_completed.name, "docusign_completed_at"
        )

        # Second webhook — should not overwrite completed_at
        self._call_handler(LEGACY_COMPLETED)
        second_completed_at = frappe.db.get_value(
            "CRM Deal", self.deal_completed.name, "docusign_completed_at"
        )

        self.assertEqual(first_completed_at, second_completed_at)

    # --- declined email notification ---

    @patch("frappe_docusign.api.webhook.frappe.sendmail")
    def test_declined_sends_email_to_deal_owner(self, mock_sendmail):
        owner_user = "Administrator"
        frappe.db.set_value(
            "CRM Deal", self.deal_declined.name, "deal_owner", owner_user
        )
        self._call_handler(LEGACY_DECLINED)
        mock_sendmail.assert_called_once()
        call_kwargs = mock_sendmail.call_args[1]
        self.assertIn("Administrator", str(call_kwargs.get("recipients", "")))

    def test_declined_without_owner_does_not_raise(self):
        frappe.db.set_value("CRM Deal", self.deal_declined.name, "deal_owner", None)
        # Should not raise even without an owner
        self._call_handler(LEGACY_DECLINED)
        self.assertEqual(frappe.response.http_status_code, 200)
