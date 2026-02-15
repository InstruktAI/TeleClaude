---
id: project/procedure/escalation
type: procedure
scope: project
description: Step-by-step escalation procedure for the help desk operator.
audience: [admin, help-desk]
---

# Escalation — Procedure

## Goal

Hand a customer conversation to a human admin when automated resolution is insufficient, ensuring the customer is informed and the admin receives full context.

## Preconditions

- The current session has `human_role: customer`.
- An escalation trigger has been identified (see escalation policy).
- The `teleclaude__escalate` tool is available in the session.

## Steps

1. Recognize the escalation trigger: low confidence, explicit human request, billing/security topic, or policy match.
2. Summarize the conversation context so the admin can act without re-reading the full transcript.
3. Call `teleclaude__escalate` with:
   - `customer_name`: the customer's name or identifier
   - `reason`: concise explanation of why escalation is needed
   - `context_summary`: brief summary of the conversation so far (optional but recommended)
4. Inform the customer that an admin has been notified and will join the conversation shortly.
5. Wait for the admin to handle the conversation via the relay channel. Do not continue resolving the issue.
6. When the admin hands back with `@agent`, resume the conversation naturally, acknowledging what was discussed during the relay.

## Outputs

- A Discord escalation thread created in the escalation forum.
- Admin notification sent.
- Relay mode activated on the session.
- Customer informed of the handoff.

## Recovery

- If `teleclaude__escalate` returns an error (e.g., Discord unavailable), inform the customer that escalation could not be completed and suggest they try again shortly or provide an alternative contact method.
- If the admin does not respond within a reasonable time, the customer can continue the conversation with the AI (relay mode will be cleared on `@agent` handback).
