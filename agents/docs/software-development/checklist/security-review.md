---
description: Security review checklist for boundary validation, secrets, and access controls.
id: software-development/checklist/security-review
requires:
  - software-development/standards/security-awareness
scope: domain
type: checklist
---

# Security Review Checklist

- [ ] Secrets are not committed or logged.
- [ ] Inputs are validated at system boundaries.
- [ ] Access control checks exist on sensitive operations.
- [ ] Error messages avoid leaking sensitive details.
- [ ] Safe defaults are enforced for permissions and exposure.
- [ ] High‑risk changes were escalated for review.
