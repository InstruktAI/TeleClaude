---
id: 'project/procedure/escalation'
type: 'procedure'
scope: 'project'
description: 'Step-by-step procedure for escalating a customer conversation to an admin.'
audience:
  - help-desk
---

# Escalation — Procedure

## Required reads

@docs/project/policy/escalation.md
@docs/project/spec/tools/escalation.md

## Trigger

One of the escalation policy triggers is met.

## Steps

1. Recognize the escalation trigger (see policy).
2. Call `teleclaude__escalate` with:
   - `customer_name`: the customer's display name
   - `reason`: a concise summary of why escalation is needed
   - `context_summary`: (optional) relevant conversation context
3. Inform the customer that a human will follow up shortly.
4. Continue handling other queries normally while waiting.
5. When the admin sends `@agent` in the relay thread, the conversation returns to you with context from the admin exchange.
6. Acknowledge what was discussed and continue naturally.

## Outcome

The customer receives timely human attention for issues beyond AI capabilities. The operator resumes with full context after handback.
