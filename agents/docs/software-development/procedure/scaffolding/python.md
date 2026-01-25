---
description:
  Scaffold a Python repo with standard tooling, Makefile targets, and uv-managed
  dependencies.
id: software-development/procedure/scaffolding/python
scope: domain
type: procedure
---

# Python — Procedure

## Goal

Create a predictable Python project skeleton with standardized tooling and verification commands.

- `pyproject.toml` (single source of truth for deps and tool config)
- `Makefile` with standard targets
- `uv` for dependency/environment management
- Optional wrapper scripts (called by Makefile): `bin/format.sh`, `bin/lint.sh`, `bin/test.sh`

1. **Initialize project metadata**
   - Create `pyproject.toml` with name, version, Python requirement, and tool configuration sections.
   - Create `teleclaude.yml` with `business.domains` for doc filtering.

2. **Define Makefile targets**
   - `make format` (formatters as configured)
   - `make lint` (lint + type check)
   - `make test-unit` (unit tests)
   - `make test-e2e` (integration tests, if applicable)
   - `make test` or `make test-all` (full suite)

3. **Wire tool configuration**
   - Configure format/lint/type tools inside `pyproject.toml`.
   - Ensure Makefile calls the configured tools (or wrapper scripts).

4. **Set up uv**
   - Ensure `uv` is the standard for sync/install.
   - `uv sync` should bootstrap the environment cleanly.
   - Use `.venv/bin/python` for all repo tooling; avoid system Python.

5. **Verify scaffold**
   - `make format`
   - `make lint`
   - `make test-unit`
   - `make test-e2e` (if applicable)

- Makefile targets exist and run successfully.
- `pyproject.toml` contains tool configuration.
- `uv sync` works without manual venv setup.

- TBD.

- TBD.

- TBD.

- TBD.

## Preconditions

- TBD.

## Steps

- TBD.

## Outputs

- TBD.

## Recovery

- TBD.
