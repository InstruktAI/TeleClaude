# Roadmap

> **Last Updated**: 2026-01-13
> **Status Legend**: `[ ]` = Pending | `[.]` = Ready | `[>]` = In Progress
> (DONE work is tracked in [delivered.md](./delivered.md))

---

## Work Preparation Pipeline

---

## Model Boundary Consolidation

- [x] model-boundary-consolidation
  Define one source of truth for resource models, use Pydantic at boundaries only, and remove ad-hoc payload shapes.

---

## Cache Architecture Alignment

- [.] smart-cache-policy-matrix
  Implement matrix-driven cache behavior (serve stale + refresh) across all REST reads.
- [.] cache-read-path-normalization
  Ensure all REST endpoints read from cache only; no direct remote pulls in handlers.

---

## Test Suite Quality Cleanup

- [.] test-cleanup
  Refactor test suite to verify observable behavior, add docstrings, document system boundaries.
