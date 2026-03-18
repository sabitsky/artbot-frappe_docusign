"""
DocuSign JWT Grant authentication.

Provides get_access_token() which caches the access token for 55 minutes.
Call invalidate_token_cache() whenever DocuSign returns a 401 so the next
request fetches a fresh token.

Consent URL (one-time setup, run in browser):
    {auth_server}/oauth/auth
        ?response_type=code
        &scope=signature%20impersonation
        &client_id={integration_key}
        &redirect_uri={frappe_site_url}/api/method/frappe_docusign.api.auth.oauth_callback
"""
import time

import frappe
import jwt
import requests

_CACHE_KEY = "docusign_access_token"
_TOKEN_TTL_SEC = 3300  # cache for 55 min (token is valid 60 min)


def get_access_token() -> str:
    """Return a valid DocuSign access token, using cache when available."""
    cached = frappe.cache().get_value(_CACHE_KEY)
    if cached:
        return cached
    return _fetch_and_cache_token()


def invalidate_token_cache() -> None:
    """Remove cached token. Call on DocuSign 401 to force re-auth."""
    frappe.cache().delete_value(_CACHE_KEY)


def _fetch_and_cache_token() -> str:
    settings = frappe.get_single("DocuSign Settings")

    if not settings.private_key:
        frappe.throw(
            "DocuSign RSA private key is not configured in DocuSign Settings.",
            frappe.ValidationError,
        )

    now = int(time.time())
    assertion = jwt.encode(
        {
            "iss": settings.integration_key,
            "sub": settings.user_id,
            "aud": settings.auth_server.replace("https://", ""),
            "iat": now,
            "exp": now + 3600,
            "scope": "signature impersonation",
        },
        settings.private_key,
        algorithm="RS256",
    )

    resp = requests.post(
        f"{settings.auth_server}/oauth/token",
        data={
            "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
            "assertion": assertion,
        },
        timeout=30,
    )
    resp.raise_for_status()

    token = resp.json()["access_token"]
    frappe.cache().set_value(_CACHE_KEY, token, expires_in_sec=_TOKEN_TTL_SEC)
    return token


@frappe.whitelist(allow_guest=True)
def oauth_callback():
    """
    Handles the OAuth consent redirect from DocuSign (one-time setup only).
    After the admin visits the consent URL and approves, DocuSign redirects here.
    No token exchange is performed — JWT Grant does not require storing the code.
    """
    error = frappe.request.args.get("error")
    if error:
        error_description = frappe.request.args.get("error_description", "")
        frappe.throw(f"DocuSign OAuth error: {error}. {error_description}")

    code = frappe.request.args.get("code")
    if code:
        return (
            "<html><body style='font-family:sans-serif;padding:40px'>"
            "<h2>DocuSign consent granted successfully.</h2>"
            "<p>You can close this tab and return to Frappe CRM.</p>"
            "<p>The integration is now authorised to use JWT Grant authentication.</p>"
            "</body></html>"
        )

    frappe.throw("Invalid OAuth callback: no code or error received.")
