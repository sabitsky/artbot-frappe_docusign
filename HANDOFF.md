# Morning Handoff — frappe_docusign Installation

Instructions for the server admin. Follow in order. After each step, verify the expected result before proceeding.

---

## Part 1 — Install the App (15–20 min)

```bash
cd /home/frappe/frappe-bench

# 1. Download the app
bench get-app https://github.com/sabitsky/artbot-frappe_docusign

# 2. Find out your site name if unsure
bench list-sites

# 3. Install on your site (replace crm.yourdomain.com)
bench --site crm.yourdomain.com install-app frappe_docusign

# 4. Apply migrations (creates DocType, custom fields, CRM stages, form script)
bench --site crm.yourdomain.com migrate

# 5. Build JS assets
bench build --app frappe_docusign

# 6. Restart
bench restart
```

**Expected after step 6:**
- `bench --site crm.yourdomain.com list-apps` shows `frappe_docusign`
- No errors in the `migrate` output (warnings about existing stages are OK)

---

## Part 2 — Quick Smoke Test (5 min)

1. Open `https://crm.yourdomain.com/app/docusign-settings`
   → Settings form should load with fields: Environment, Integration Key, Account ID, User ID, RSA Private Key, Webhook HMAC Secret, Enabled.

2. Open any CRM Deal → scroll to the bottom
   → A **DocuSign** section should appear (collapsed) with fields: Envelope ID, Status, Sent At, Completed At, Envelope Link, Last Error.

3. Change the deal's stage to **Proposal Sent**
   → A **DocuSign → Send for Signing** button should appear in the top-right button group.

If any of these three checks fail — **stop and report back** (see Part 5).

---

## Part 3 — Run the Tests (10 min)

```bash
# Enable tests on the site (one-time)
bench --site crm.yourdomain.com set-config allow_tests 1

# Run all frappe_docusign tests
bench --site crm.yourdomain.com run-tests --app frappe_docusign
```

**Expected:** All tests pass. Note any failures and send me the output.

If you want to run individual modules:
```bash
bench --site crm.yourdomain.com run-tests --app frappe_docusign \
    --module frappe_docusign.docusign.doctype.docusign_settings.test_docusign_settings

bench --site crm.yourdomain.com run-tests --app frappe_docusign \
    --module frappe_docusign.api.tests.test_auth

bench --site crm.yourdomain.com run-tests --app frappe_docusign \
    --module frappe_docusign.api.tests.test_envelope

bench --site crm.yourdomain.com run-tests --app frappe_docusign \
    --module frappe_docusign.api.tests.test_webhook
```

---

## Part 4 — Run the Diagnostic Endpoint (2 min)

This verifies the CRM Deal field names on your specific installation.

```bash
# Get your API key/secret from Frappe: Settings → My Account → API Access
curl -s \
  "https://crm.yourdomain.com/api/method/frappe_docusign.api.diagnostic.get_crm_deal_fields" \
  -H "Authorization: token YOUR_API_KEY:YOUR_API_SECRET" | python3 -m json.tool
```

**Send me the full JSON output.** I need to see:
- `stage_candidates` — which of `pipeline_stage` / `stage` is actually on your CRM Deal
- `email_candidates` — which of `email` / `contact_email` / `customer_email`
- `name_candidates` — which of `lead_name` / `contact_name` / `customer_name`

---

## Part 5 — What to Report Back

Please send me:

1. Output of `bench --site {site} list-apps` (confirm frappe_docusign is installed)
2. Result of the 3 smoke test checks (pass / fail / error message)
3. Full test run output (pass count, any failures with traceback)
4. Full JSON output from the diagnostic endpoint
5. Any error messages from the `migrate` step

---

## If Something Goes Wrong

| Symptom | Fix |
|---------|-----|
| DocuSign Settings page 404 | `bench --site {site} migrate && bench restart` |
| DocuSign section missing on Deal | `bench build --app frappe_docusign && bench restart` |
| Send for Signing button missing | Stage must be exactly "Proposal Sent" — check if the stage was created |
| "Could not create CRM Stage" in Error Log | Create the stages manually in CRM → Settings → Stages: Lead, Qualified, Proposal Sent, Contract Sent, Contract Signed, Onboarding |
| Test failures with import errors | `pip install PyJWT cryptography requests` in the bench virtualenv |

Full troubleshooting reference: see `SETUP.md` in this repo.

---

> **Note:** DocuSign credentials are NOT needed for Parts 1–4. The tests use mocks. We configure DocuSign Settings separately once you confirm everything above is working.
