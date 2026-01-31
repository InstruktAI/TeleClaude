---
description: Security review checklist for boundary validation, secrets, and access controls.
id: software-development/checklist/security-review
scope: domain
type: checklist
---

# Security Review — Checklist

## Required reads

- @~/.teleclaude/docs/software-development/policy/security-awareness.md

## Purpose

Verify that security-critical changes meet baseline policy before merging.

## Preconditions

- Relevant code changes are identified and ready for review.

## Checks

- [ ] Secrets are not committed or logged.
- [ ] Inputs are validated at system boundaries.
- [ ] Access control checks exist on sensitive operations.
- [ ] Error messages avoid leaking sensitive details.
- [ ] Safe defaults are enforced for permissions and exposure.
- [ ] High-risk changes were escalated for review.

## Recovery

- If any check fails, block merge and file follow-up tasks.
