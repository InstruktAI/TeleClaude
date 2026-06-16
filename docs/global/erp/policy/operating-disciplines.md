---
description: Disciplines for agents acting on a company's ERPNext over the API — introspect before writing, draft-first, idempotency, scoped identity, deliberate submission.
---

# ERP Operating Disciplines — Policy

## Rules

- **Introspect before the first write.** Before creating or updating any DocType on an
  instance not operated before, call `/api/v2/doctype/{doctype}/meta` and satisfy every
  `reqd` field, `Link` target, and child `Table` it reports. Never hardcode field lists —
  sites carry custom mandatory fields that exist in no model's memory.
- **Create draft-first.** New documents are created at `docstatus = 0` (draft). Submission
  (`docstatus = 1`) and any outbound send are separate, deliberate acts — never an implicit
  side effect of creation.
- **Check before create (idempotency).** ERPNext does not deduplicate. Search by a natural
  key (email, name) before creating a Customer, Quotation, or Invoice.
- **Operate as the scoped identity.** Use the company's operator credentials, never the
  administrator's god-mode key, for company-level work — so every mutation is attributable
  and bounded to that company's scope.
- **Submit and cancel deliberately.** `docstatus` is `0` draft, `1` submitted (immutable),
  `2` cancelled. Submitted financial documents are changed via cancel-and-amend, never
  edited. Verify the exact submit mechanism against a draft on each new instance before
  relying on it.

## Rationale

ERPNext is a system of record with financial and legal weight. A wrong field on an invoice
or a duplicated customer is a defect in a ledger, not a cosmetic bug. These rules place the
reversibility line inside the agent: cheap, reversible operations (reading, drafting) run
freely; irreversible or outbound ones (submit, send, post) are deliberate. Runtime
introspection converts approximate memory into exact, per-tenant correctness, and scoped
identity keeps a mistake contained to one company.

## Scope

All agent operations against any company's ERPNext data over the REST API.

## Enforcement

- A create that hardcodes fields without a preceding `/meta` read on a new instance is a defect.
- A submit or outbound send issued as an undeliberate side effect of creation is a defect.
- Company-level work performed with the administrator's god-mode key instead of the company's
  scoped operator key is a defect.
- Duplicate records traceable to a missing check-before-create are a defect.

## Exceptions

None.

## See Also

- ~/.teleclaude/docs/erp/concept/operation-model.md
- ~/.teleclaude/docs/erp/concept/multi-tenancy.md
