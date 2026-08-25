---
description: Direct process-environment access in runtime Python is blocked unless the access belongs to a narrow, explicitly classified boundary.
delivered_by:
  - config-env-guardrail
---

# Direct Environment Access Guardrail — Spec

## Required reads

- @docs/project/spec/domain/config.md
- @docs/project/policy/python-linting.md

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

### Use cases

#### UC-CFG-SOURCE-1: An unclassified runtime environment access is blocked

```gherkin
Given an agent adds a direct process-environment access to runtime Python outside the configuration boundary
And the access is not explicitly classified as an allowed boundary use
When the repository quality gate inspects the changed source
Then the quality gate fails
And the finding identifies the source location
And the finding directs configuration values through file-backed typed configuration
```

#### UC-CFG-SOURCE-2: An explicitly classified boundary access remains accepted

```gherkin
Given runtime Python directly accesses the process environment for configuration loading or interpolation, bootstrap or an internal process signal, ambient host state, child-process environment construction, or an explicit temporary migration
And the source classifies that access at its location
When the repository quality gate inspects the source
Then that access does not produce a direct-environment-access finding
And removing a temporary bypass also removes its local exception
```
