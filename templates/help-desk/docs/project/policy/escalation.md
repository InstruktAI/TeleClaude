---
id: 'project/policy/escalation'
type: 'policy'
scope: 'project'
description: 'When and why to escalate a customer conversation to a human admin.'
audience:
  - help-desk
---

# Escalation — Policy

## Required reads

## Rules

- Escalate when the customer explicitly requests a human.
- Escalate billing or payment issues that require account access.
- Escalate security concerns or account compromise reports.
- Escalate when confidence in the answer is low after two attempts.
- Do not escalate routine questions that are covered by documentation.

## Rationale

Escalation protects customers from incorrect answers on high-stakes topics and ensures human oversight where AI capabilities are insufficient.

## Scope

Applies to all customer-facing sessions handled by the help desk operator.

## Enforcement

The operator uses `teleclaude__escalate` to create a relay thread and notify admins.

## Exceptions

None defined yet. Use `/author-knowledge` to refine escalation thresholds.
