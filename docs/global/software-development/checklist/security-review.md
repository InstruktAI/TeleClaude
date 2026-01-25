---
description:
  Security review checklist for boundary validation, secrets, and access
  controls.
id: software-development/checklist/security-review
scope: domain
type: checklist
---

# Security Review — Checklist

## Required reads

- @~/.teleclaude/docs/software-development/policy/security-awareness

## Goal

- Verify security-critical changes meet baseline policy.

## Preconditions

- Relevant code changes are identified and ready for review.

## Steps

- [ ] Secrets are not committed or logged.
- [ ] Inputs are validated at system boundaries.
- [ ] Access control checks exist on sensitive operations.
- [ ] Error messages avoid leaking sensitive details.
- [ ] Safe defaults are enforced for permissions and exposure.
- [ ] High‑risk changes were escalated for review.

## Outputs

- Security review completed or escalation required.

## Recovery

- If any check fails, block merge and file follow-up tasks.
