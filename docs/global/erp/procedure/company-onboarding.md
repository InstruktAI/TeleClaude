---
description: Onboard a company onto the shared ERPNext instance — the administrator agent creates the company and a permission-scoped operator identity, then records its credentials with the company.
activation_trigger: Onboarding a new company onto the shared ERPNext instance for agent operation.
---

# ERP Company Onboarding — Procedure

## Goal

A new company operable on the shared ERPNext instance by a dedicated operator identity whose
permissions and credentials are scoped to that company alone.

## Preconditions

- The shared ERPNext instance is reachable and the **administrator agent** holds its
  god-mode credentials.
- A company slug (the tenant identity used across TeleClaude).

## Steps

### 1. Create the company in ERPNext

Create the `Company` record (native multi-company). This is the data boundary every later
permission and document references.

### 2. Create the scoped operator user

Create an ERPNext user to act as the company's operator agent, with roles and permission
rules limited to that company's data (multi-company permission scoping). It must not carry
System Manager / god-mode.

### 3. Mint the operator API key

Generate the operator user's `api_key`/`api_secret`. This key _is_ the company's scope —
it authenticates as that user and inherits its permission box.

### 4. Record the credentials with the company

Store the operator credentials as that company's ERP credentials (the company-scoped
credential home; the company-config layer owns where). The operator agent loads these to
operate; the administrator's god-mode credentials are never copied here.

### 5. Verify scope

Authenticate with the operator key (`/api/method/frappe.auth.get_logged_user` returns the
operator user) and confirm it can read its own company and cannot reach another company's
data.

## Outputs

- A `Company` record on the shared instance.
- A permission-scoped operator user + API key.
- Operator credentials recorded with the company.
- Verified scope isolation.

## Recovery

- Re-running key generation rotates the operator secret; update the company's stored
  credentials after any rotation.
- A decrypt error on an existing operator account signals a stale `encryption_key` in the
  instance's `site_config.json` (restore artifact) — fix the encryption key, not the token.

## Discipline

This procedure mints long-lived, permission-bearing credentials on a live financial system.
The failure modes are over-privilege and leakage: granting the operator more than its one
company, or copying the administrator's god-mode key into a company's store. Verify the
permission box before handing the key over (step 5 must prove the operator cannot see other
companies), and never let an operator identity carry System Manager. Never echo a secret;
record it directly in the company's credential store.

## See Also

- ~/.teleclaude/docs/erp/concept/multi-tenancy.md
- ~/.teleclaude/docs/erp/procedure/person-onboarding.md
