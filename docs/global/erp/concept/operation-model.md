---
description: How agents operate ERPNext — raw Frappe v2 REST plus runtime introspection, deliberately without a CLI or generated client, agent-first.
---

# ERP Operation Model — Concept

## What

Agents operate ERPNext directly over its REST API. Nothing sits between the agent and the
instance — no CLI, no generated client.

- **Transport.** Frappe v2 REST. Every business object is reached through one generic
  envelope: `/api/v2/document/{doctype}` for CRUD, `/api/v2/doctype/{doctype}/meta` for
  schema, `/api/v2/document/{doctype}/{name}/method/{method}` for document actions.
  `{doctype}` is a parameter — the same handful of verbs operate all ~800 DocTypes.
- **Truth at runtime.** Per-instance schema (fields, mandatory flags, custom fields) is read
  live from `/meta`, never hardcoded. Memory supplies the pattern; the instance supplies the
  truth.
- **Auth.** A token in the header: `Authorization: token <api_key>:<api_secret>`. The token
  belongs to an ERPNext user, whose roles and permissions bound what the call can do.
- **Business flow.** Lead/Customer → Quotation (the "proposal") → Sales Order →
  Sales Invoice → Payment Entry.

## Why

- **No CLI.** The REST surface is uniform across every DocType and agents are fluent in it.
  A hand-written CLI would re-encode that surface as frozen verbs and drift against
  per-instance customizations — maintenance cost for no new capability.
- **No generated client.** The only available OpenAPI spec describes the generic
  six-operation envelope, not per-DocType schemas, so a generated client is functionally
  identical to raw HTTP, and any client that encoded per-DocType shapes would be wrong for
  some tenant. The generic pattern plus runtime `/meta` is correct everywhere, maintenance-free.
- **Agent-first.** Humans are product owners and observers; agents operate. The instance UI
  is an observability surface, not the operating path — so the API must be complete enough
  that no operation ever requires it.

## See Also

- ~/.teleclaude/docs/erp/concept/multi-tenancy.md
- ~/.teleclaude/docs/erp/policy/operating-disciplines.md
