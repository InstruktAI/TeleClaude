---
description: Onboard a person into a company's ERPNext — create a permission-scoped ERPNext user for that company and send them a login email.
activation_trigger: Onboarding a human user into a specific company's ERPNext with scoped access.
---

# ERP Person Onboarding — Procedure

## Goal

A person can log into ERPNext with access scoped to a single company.

## Preconditions

- The company is already onboarded (its `Company` record and operator identity exist).
- The person's name and email.

## Steps

### 1. Create the ERPNext user

Create an ERPNext user for the person.

### 2. Scope permissions to the company

Assign roles and permission rules that limit the user to that company's data — the same
multi-company permission boundary the operator identity uses. The person sees only their
company.

### 3. Send the login email

Trigger ERPNext's welcome/login email so the person can set credentials and sign in.

## Outputs

- A permission-scoped ERPNext user for the person.
- A login email delivered.

## Recovery

- If the email does not arrive, confirm the instance's email module is configured and
  resend the welcome notification.

## Discipline

The risk here is the same over-privilege trap as company onboarding: a person scoped too
broadly can read another company's ledger. Confirm the permission box limits the user to the
intended company before issuing the login. Email delivery depends on the instance's ERPNext
email configuration being in place — do not assume it; verify a send.

## See Also

- ~/.teleclaude/docs/erp/concept/multi-tenancy.md
- ~/.teleclaude/docs/erp/procedure/company-onboarding.md
