# Roadmap

> **Last Updated**: 2026-01-14
> **Status Legend**: `[ ]` = Pending | `[.]` = Ready | `[>]` = In Progress
> (DONE work is tracked in [delivered.md](./delivered.md))

---

## Work Preparation Pipeline

---

## Model Boundary Consolidation

- [>] model-boundary-consolidation
  Define one source of truth for resource models, use Pydantic at boundaries only, and remove ad-hoc payload shapes.

---

## Cache Improvements

- [.] cache-startup-warmup
  Warmup remote projects on daemon startup and add digest-based invalidation to heartbeats.

---

## Test Suite Quality Cleanup

- [.] test-cleanup
  Refactor test suite to verify observable behavior, add docstrings, document system boundaries.
