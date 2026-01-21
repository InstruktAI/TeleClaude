---
id: standard/definition-of-done
type: standard
scope: project
description: Quality gates and verification steps required for completing code changes.
---

## Rule

- Complete the required logic and implement the intended behavior.
- Add tests (unit, and integration when boundaries are touched).
- Run `make test` and ensure it passes.
- Run `make lint` and resolve all findings.
- Restart the daemon (`make restart`) and verify health (`make status`).
- Leave no temporary artifacts or duplicate databases.

## Rationale

- Ensures correctness, regression safety, and operational readiness.

## Scope

- Applies to all code changes in this repository.

## Enforcement or checks

- CI/test runs must pass.
- Manual confirmation of daemon health is required after changes.

## Exceptions or edge cases

- None; skipping checks is considered incomplete work.
