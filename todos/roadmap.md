# Roadmap

> **Last Updated**: 2026-01-23
> **Status Legend**: `[ ]` = Pending | `[.]` = Ready | `[>]` = In Progress
> (DONE work is tracked in [delivered.md](./delivered.md))

---

## Eliminate Raw SQL from DB Layer

- [ ] db-raw-sql-cleanup

Convert inline SQL in db.py to SQLModel/SQLAlchemy ORM and enforce via pre-commit hook.

## Test Suite Quality Cleanup

- [ ] repo-cleanup

Refactor test suite to verify observable behavior, add docstrings, document system boundaries.

## Release Automation Pipeline

- [ ] release-automation

Automated AI-driven release pipeline with Claude Code and Codex CLI inspectors.
