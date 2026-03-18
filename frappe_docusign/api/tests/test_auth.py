"""
TDD tests for frappe_docusign.api.auth

Tests cover:
  - token fetched from DocuSign on cache miss
  - token cached and reused on subsequent calls
  - JWT payload contains correct claims (iss, sub, aud, scope, exp)
  - cache invalidated by invalidate_token_cache()
  - fresh token fetched after cache invalidation
  - HTTP error from DocuSign propagates as exception
  - missing private key raises ValidationError

Run:
    bench --site {site} run-tests --app frappe_docusign \
        --module frappe_docusign.api.tests.test_auth
"""
import time
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase


def _generate_rsa_private_key_pem() -> str:
    """Generate a throwaway 2048-bit RSA key for use in unit tests."""
    from cryptography.hazmat.backends import default_backend
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
        backend=default_backend(),
    )
    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()


# Generated once per test run to avoid repeated crypto slowness
_TEST_PRIVATE_KEY = _generate_rsa_private_key_pem()


class TestGetAccessToken(FrappeTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Write test credentials into DocuSign Settings once for the whole suite
        settings = frappe.get_single("DocuSign Settings")
        settings.integration_key = "test-integration-key"
        settings.account_id = "test-account-id"
        settings.base_url = "https://demo.docusign.net/restapi"
        settings.auth_server = "https://account-d.docusign.com"
        settings.environment = "Sandbox"
        settings.user_id = "test-user-id-guid"
        settings.enabled = 1
        settings.private_key = _TEST_PRIVATE_KEY
        settings.save(ignore_permissions=True)
        frappe.db.commit()

    def setUp(self):
        # Always start each test with an empty cache
        from frappe_docusign.api.auth import invalidate_token_cache
        invalidate_token_cache()

    # --- helpers ---

    def _mock_response(self, token: str = "test-token") -> MagicMock:
        resp = MagicMock()
        resp.json.return_value = {"access_token": token}
        resp.raise_for_status = MagicMock()
        return resp

    # --- tests ---

    @patch("frappe_docusign.api.auth.requests.post")
    def test_returns_token_on_cache_miss(self, mock_post):
        mock_post.return_value = self._mock_response("fresh-token")

        from frappe_docusign.api.auth import get_access_token
        token = get_access_token()

        self.assertEqual(token, "fresh-token")
        mock_post.assert_called_once()

    @patch("frappe_docusign.api.auth.requests.post")
    def test_calls_correct_docusign_token_endpoint(self, mock_post):
        mock_post.return_value = self._mock_response()

        from frappe_docusign.api.auth import get_access_token
        get_access_token()

        url = mock_post.call_args[0][0]
        self.assertIn("account-d.docusign.com/oauth/token", url)

    @patch("frappe_docusign.api.auth.requests.post")
    def test_uses_jwt_bearer_grant_type(self, mock_post):
        mock_post.return_value = self._mock_response()

        from frappe_docusign.api.auth import get_access_token
        get_access_token()

        data = mock_post.call_args[1]["data"]
        self.assertEqual(
            data["grant_type"],
            "urn:ietf:params:oauth:grant-type:jwt-bearer",
        )

    @patch("frappe_docusign.api.auth.requests.post")
    def test_second_call_uses_cache_not_api(self, mock_post):
        mock_post.return_value = self._mock_response("cached-token")

        from frappe_docusign.api.auth import get_access_token
        t1 = get_access_token()
        t2 = get_access_token()

        mock_post.assert_called_once()   # only one HTTP call
        self.assertEqual(t1, t2)
        self.assertEqual(t1, "cached-token")

    @patch("frappe_docusign.api.auth.requests.post")
    def test_jwt_payload_contains_correct_iss(self, mock_post):
        mock_post.return_value = self._mock_response()

        from frappe_docusign.api.auth import get_access_token
        get_access_token()

        import jwt as pyjwt
        assertion = mock_post.call_args[1]["data"]["assertion"]
        claims = pyjwt.decode(assertion, options={"verify_signature": False})
        self.assertEqual(claims["iss"], "test-integration-key")

    @patch("frappe_docusign.api.auth.requests.post")
    def test_jwt_payload_contains_correct_sub(self, mock_post):
        mock_post.return_value = self._mock_response()

        from frappe_docusign.api.auth import get_access_token
        get_access_token()

        import jwt as pyjwt
        assertion = mock_post.call_args[1]["data"]["assertion"]
        claims = pyjwt.decode(assertion, options={"verify_signature": False})
        self.assertEqual(claims["sub"], "test-user-id-guid")

    @patch("frappe_docusign.api.auth.requests.post")
    def test_jwt_payload_contains_correct_aud(self, mock_post):
        mock_post.return_value = self._mock_response()

        from frappe_docusign.api.auth import get_access_token
        get_access_token()

        import jwt as pyjwt
        assertion = mock_post.call_args[1]["data"]["assertion"]
        claims = pyjwt.decode(assertion, options={"verify_signature": False})
        self.assertEqual(claims["aud"], "account-d.docusign.com")

    @patch("frappe_docusign.api.auth.requests.post")
    def test_jwt_payload_contains_required_scopes(self, mock_post):
        mock_post.return_value = self._mock_response()

        from frappe_docusign.api.auth import get_access_token
        get_access_token()

        import jwt as pyjwt
        assertion = mock_post.call_args[1]["data"]["assertion"]
        claims = pyjwt.decode(assertion, options={"verify_signature": False})
        self.assertIn("signature", claims["scope"])
        self.assertIn("impersonation", claims["scope"])

    @patch("frappe_docusign.api.auth.requests.post")
    def test_jwt_expiry_is_one_hour_from_now(self, mock_post):
        mock_post.return_value = self._mock_response()

        before = int(time.time())
        from frappe_docusign.api.auth import get_access_token
        get_access_token()
        after = int(time.time())

        import jwt as pyjwt
        assertion = mock_post.call_args[1]["data"]["assertion"]
        claims = pyjwt.decode(assertion, options={"verify_signature": False})

        self.assertGreaterEqual(claims["exp"], before + 3600)
        self.assertLessEqual(claims["exp"], after + 3600)

    @patch("frappe_docusign.api.auth.requests.post")
    def test_http_error_propagates(self, mock_post):
        import requests as req_lib
        err_resp = MagicMock()
        err_resp.raise_for_status.side_effect = req_lib.HTTPError("401 Unauthorized")
        mock_post.return_value = err_resp

        from frappe_docusign.api.auth import get_access_token
        with self.assertRaises(req_lib.HTTPError):
            get_access_token()

    def test_invalidate_cache_clears_stored_token(self):
        frappe.cache().set_value("docusign_access_token", "old-token")

        from frappe_docusign.api.auth import invalidate_token_cache
        invalidate_token_cache()

        self.assertIsNone(frappe.cache().get_value("docusign_access_token"))

    @patch("frappe_docusign.api.auth.requests.post")
    def test_fetches_new_token_after_invalidation(self, mock_post):
        mock_post.return_value = self._mock_response("first-token")

        from frappe_docusign.api.auth import get_access_token, invalidate_token_cache
        t1 = get_access_token()

        invalidate_token_cache()
        mock_post.return_value = self._mock_response("second-token")
        t2 = get_access_token()

        self.assertEqual(t1, "first-token")
        self.assertEqual(t2, "second-token")
        self.assertEqual(mock_post.call_count, 2)

    def test_missing_private_key_raises_validation_error(self):
        # Temporarily clear the private key
        original = frappe.db.get_value("DocuSign Settings", None, "private_key")
        frappe.db.set_value("DocuSign Settings", "DocuSign Settings", "private_key", "")
        frappe.db.commit()

        try:
            from frappe_docusign.api.auth import get_access_token
            with self.assertRaises(frappe.ValidationError):
                get_access_token()
        finally:
            frappe.db.set_value(
                "DocuSign Settings", "DocuSign Settings", "private_key", original
            )
            frappe.db.commit()
