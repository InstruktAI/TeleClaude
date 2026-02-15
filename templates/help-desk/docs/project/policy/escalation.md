---
id: project/policy/escalation
type: policy
scope: project
description: When and why to escalate a customer conversation to an admin.
audience: [admin, help-desk]
---

# Escalation — Policy

## Rules

- Escalate when confidence in the answer is low and the customer's issue requires authoritative resolution.
- Escalate when the customer explicitly requests to speak with a human.
- Escalate for billing disputes, refund requests, or payment issues that require account-level access.
- Escalate for security-sensitive topics: account compromise, data deletion, access control changes.
- Escalate for legal or compliance questions that require human judgment.
- Do not escalate for questions answerable from documentation. Search first using `get_context`.
- Do not escalate for general product questions, even if complex. Attempt resolution first.
- Always inform the customer that an admin has been notified before the relay activates.

## Rationale

- Customers expect timely resolution. Escalation is a tool for when AI-handled resolution is insufficient, not a default fallback.
- Billing and security topics carry legal and financial risk that warrants human oversight.
- Explicit human requests must be honored to maintain trust.

## Scope

- Applies to all customer-facing help desk sessions.

## Enforcement

- The operator brain references this policy via Required reads.
- The `teleclaude__escalate` tool enforces that only customer sessions can invoke it.

## Exceptions

- None.
