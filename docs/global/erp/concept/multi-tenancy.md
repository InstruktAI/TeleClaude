---
description: One shared ERPNext instance serves many companies via native multi-company plus role permissions; each company is operated by a permission-scoped operator agent identity minted by an administrator agent.
---

# ERP Multi-Tenancy — Concept

## What

A single shared ERPNext instance hosts many companies. Isolation is ERPNext's own —
**native multi-company** (the `Company` doctype) plus **role-and-permission scoping** — not
one heavyweight instance per customer.

Two agent identities, two scopes:

- **Administrator agent** — holds the instance's global (god-mode) credentials. It onboards
  new companies: creates the `Company` in ERPNext, then mints a **scoped operator identity**
  for it. It never shares its secrets with operators.
- **Operator agent (per company)** — an ERPNext **user + API key**, permission-boxed to one
  company. It loads only that company's credentials (from the company's own config) and can
  act only on that company's data. It never holds the administrator's secrets.

A **person** is onboarded as a scoped ERPNext user for their company — permissions for that
company only, plus a login email.

The credential maps to the identity: an operator's API key _is_ the company's scope. Loading
`<company>`'s credentials and calling the API is the whole act — the knowledge already lives
with the company, so the operation just runs.

## Why

- **No heavy instance per customer.** One instance, native multi-company isolation. Onboarding
  a company is creating a `Company` + a scoped user, not provisioning a stack.
- **Identity mirrors the boundary.** Because an operator's key is permission-scoped, the agent
  identity _is_ the isolation boundary — there is no way for a company's operator to read or
  mutate another company's data, and no way for it to reach administrator-only operations.
- **Least privilege by construction.** The administrator's god-mode credentials never leave the
  administrator. A leaked operator key exposes one company, not the instance.

## See Also

- ~/.teleclaude/docs/erp/procedure/company-onboarding.md
- ~/.teleclaude/docs/erp/procedure/person-onboarding.md
- ~/.teleclaude/docs/erp/policy/operating-disciplines.md
