---
description: Direct process-environment access in runtime Python is blocked unless
  the access belongs to a narrow, explicitly classified boundary.
---

# Direct Environment Access Guardrail — Spec

## Required reads

- @docs/local/spec/domain/config.md
- @docs/local/policy/python-linting.md

## What it is

The Python quality gate keeps runtime configuration on the file-backed typed
configuration path. A direct process-environment access outside that path is a
blocking finding unless the access is explicitly classified as configuration
loading or interpolation, bootstrap or an internal process signal, ambient host
state, or child-process environment construction.

Existing configuration bypasses remain visible as temporary exceptions while
their owning migrations are in flight. New unclassified bypasses cannot join
that set.

## Canonical fields

### Local exception classifications

- Every accepted direct process-environment access carries a local classification marker with a non-empty reason.
- A permanent exception names its allowed boundary category.
- A temporary exception names the migration todo that owns removing the access; removing the access removes its marker in the same change.
- A bare classification marker does not satisfy the exception contract.

### Use cases

#### UC-CFG-SOURCE-1: An unclassified runtime environment access is blocked

#### UC-CFG-SOURCE-2: An explicitly classified boundary access remains accepted
