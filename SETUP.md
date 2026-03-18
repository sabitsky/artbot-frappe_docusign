# frappe_docusign — Setup & Deployment Guide

## Prerequisites

- Frappe CRM installed and running on bench
- Python 3.10+
- Public HTTPS domain (required for DocuSign webhooks)
- DocuSign account (sandbox for testing; production for live)

---

## Installation (Hetzner / self-hosted bench)

```bash
cd /home/frappe/frappe-bench

# 1. Download the app from GitHub
bench get-app https://github.com/sabitsky/artbot-frappe_docusign

# 2. Install on your site
bench --site {site-name} install-app frappe_docusign

# 3. Apply migrations
#    Creates: DocuSign Settings DocType, custom fields on CRM Deal,
#             CRM pipeline stages, CRM Form Script (buttons on the deal form)
bench --site {site-name} migrate

# 4. Build JS assets (Frappe Desk fallback)
bench build --app frappe_docusign

# 5. Restart
bench restart
```

After this, open `{site}/app/docusign-settings` — the settings form should appear.

---

## DocuSign Configuration

### Step 1 — Create a DocuSign Developer Account

1. Go to <https://developers.docusign.com/> and register.
2. In the **Developer Portal → Apps** create a new app.
3. Under **Auth** add an OAuth redirect URI:
   ```
   https://{your-site}/api/method/frappe_docusign.api.auth.oauth_callback
   ```
4. Note your **Integration Key** (Client ID) and **Account ID**.

### Step 2 — Generate RSA Key Pair

1. In Developer Portal → App → **Admin** → **RSA Keypairs** → **Add RSA Keypair**.
2. Download the **private key** file.
3. The file starts with `-----BEGIN RSA PRIVATE KEY-----`.

### Step 3 — Fill in DocuSign Settings

Open `{site}/app/docusign-settings` and fill in:

| Field | Value |
|-------|-------|
| Environment | `Sandbox` (testing) / `Production` (live) |
| Integration Key | Client ID from Developer Portal |
| Account ID | Your DocuSign Account ID (GUID) |
| User ID | Your DocuSign User ID (GUID) — found in Developer Portal → My Account |
| RSA Private Key | Paste the full PEM content including `-----BEGIN / END-----` lines |
| Enabled | ✓ |

Base URL and Auth Server auto-fill when you select the environment. Save.

### Step 4 — One-Time OAuth Consent

Open this URL in a browser **while logged into your DocuSign account**:

```
https://account-d.docusign.com/oauth/auth
  ?response_type=code
  &scope=signature%20impersonation
  &client_id={integration_key}
  &redirect_uri=https://{your-site}/api/method/frappe_docusign.api.auth.oauth_callback
```

For **Production**, replace `account-d.docusign.com` with `account.docusign.com`.

Click **Allow**. You will be redirected to a success page. This step is done once per deployment.

### Step 5 — Configure DocuSign Connect (Webhook)

1. Developer Portal → **Integrations** → **Connect** → **Add Configuration**.
2. Set **URL** to:
   ```
   https://{your-site}/api/method/frappe_docusign.api.webhook.handle_docusign_event
   ```
3. Enable envelope events: **Envelope Completed**, **Envelope Declined**, **Envelope Voided**.
4. Under **Security** enable HMAC and copy the generated secret key.
5. Paste the secret into DocuSign Settings → **Webhook HMAC Secret**. Save.

---

## E2E Verification Checklist

Run this checklist top-to-bottom after deployment. Each step must pass before the next.

| # | What to do | Expected result |
|---|-----------|----------------|
| 1 | `bench --site {site} list-apps` | `frappe_docusign` listed |
| 2 | Open `{site}/app/docusign-settings` | Form loads with all 9 fields |
| 3 | Open any CRM Deal → scroll to bottom | **DocuSign** section visible with `docusign_envelope_id`, etc. |
| 4 | Open a deal with stage **Proposal Sent** | Button group **DocuSign** → **Send for Signing** appears |
| 5 | Click **Send for Signing** | Dialog opens with Name, Email, Documents table |
| 6 | Attach a PDF, fill Name & Email, click **Send via DocuSign** | Deal: `docusign_envelope_id` filled, `docusign_status` = Sent, stage = Contract Sent |
| 7 | Check client inbox | DocuSign email with signing link received |
| 8 | Sign the document in DocuSign sandbox | Webhook fires within seconds |
| 9 | Refresh the CRM Deal | `docusign_status` = Completed, stage = Contract Signed, `docusign_completed_at` filled |
| 10 | Click the **DocuSign Envelope Link** | DocuSign envelope viewer opens in browser |
| 11 | On a "Sent" deal, click **DocuSign** → **Check Status** | Status updated from DocuSign, form reloads |

---

## Updating the App

After pushing new code to GitHub:

```bash
cd apps/frappe_docusign && git pull

# Re-apply migrations (also updates CRM Form Script from the JS file)
bench --site {site-name} migrate

# Rebuild JS assets if hooks.py or JS files changed
bench build --app frappe_docusign

bench restart
```

---

## Running Tests

```bash
# Enable test mode on the site (one-time)
bench --site {site-name} set-config allow_tests 1

# Run all frappe_docusign tests
bench --site {site-name} run-tests --app frappe_docusign

# Run individual test modules
bench --site {site-name} run-tests --app frappe_docusign \
    --module frappe_docusign.api.tests.test_auth

bench --site {site-name} run-tests --app frappe_docusign \
    --module frappe_docusign.api.tests.test_envelope

bench --site {site-name} run-tests --app frappe_docusign \
    --module frappe_docusign.api.tests.test_webhook

bench --site {site-name} run-tests --app frappe_docusign \
    --module frappe_docusign.docusign.doctype.docusign_settings.test_docusign_settings
```

---

## Diagnostic Endpoint

If the **Send for Signing** button is not visible, use the diagnostic endpoint to
inspect the actual field names on CRM Deal and confirm the stage field name:

```bash
curl -s \
  "https://{site}/api/method/frappe_docusign.api.diagnostic.get_crm_deal_fields" \
  -H "Authorization: token {api_key}:{api_secret}" | python3 -m json.tool
```

Look for `stage_candidates`, `email_candidates`, `name_candidates` in the output.
If the stage field name differs from `pipeline_stage` or `stage`, open an issue on GitHub.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| "DocuSign integration is disabled" | `enabled` flag is off | DocuSign Settings → Enabled ✓ |
| "RSA private key is not configured" | Key not saved | Paste full PEM in Settings → RSA Private Key |
| 401 from DocuSign on first send | Consent not granted | Complete Step 4 (OAuth consent URL) |
| Buttons not visible on deal form | JS not built or Form Script missing | `bench build --app frappe_docusign && bench migrate && bench restart` |
| Webhook not updating the deal | Webhook not configured in DocuSign Connect | Complete Step 5; verify URL is publicly accessible |
| "Could not create CRM Stage" in Error Log | CRM Stage DocType has unexpected required fields | Create pipeline stages manually in CRM settings |
| "Neither pipeline_stage nor stage field found" in Error Log | CRM version uses a different field name | Run diagnostic endpoint, open GitHub issue with field names |
| Deal stuck on "Contract Sent" | Webhook not reaching the server | Use **Check Status** button; check DocuSign Connect delivery logs |
