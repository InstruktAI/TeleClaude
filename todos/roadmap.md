# Roadmap

> **Last Updated**: 2026-01-13
> **Status Legend**: `[ ]` = Pending | `[.]` = Ready | `[>]` = In Progress
> (DONE work is tracked in [delivered.md](./delivered.md))

---

## Work Preparation Pipeline

- [>] delivery-verification-gates
      Prevent incomplete work from being marked delivered. Workers create deferrals.md,
      reviewers verify success criteria with evidence, orchestrators resolve deferrals.

---

## Test Suite Quality Cleanup

- [>] test-cleanup
  Refactor test suite to verify observable behavior, add docstrings, document system boundaries.

---

## Model Boundary Consolidation

- [.] model-boundary-consolidation
  Define one source of truth for resource models, use Pydantic at boundaries only, and remove ad-hoc payload shapes.

---

## Cache Architecture Alignment

- [.] smart-cache-policy-matrix
  Implement matrix-driven cache behavior (serve stale + refresh) across all REST reads.
- [.] cache-read-path-normalization
  Ensure all REST endpoints read from cache only; no direct remote pulls in handlers.
