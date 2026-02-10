# Requirements: telec-config-cli

## Goal

Add an AI-friendly `telec config` command surface to read and mutate `config.yml`
from any working directory, with mandatory validation before persistence.

## Problem Statement

- Config edits are currently manual (`config.yml` direct edits), which is error-prone
  for AI and operator workflows.
- There is no dedicated `telec` command to safely read config subtrees or apply
  structured multi-key updates.
- Validation is implicit (often discovered later during runtime/restart) instead of
  explicit and immediate at edit time.

## Scope

### In scope

1. New `telec config` command family:
   - `telec config get [PATH ...]`
   - `telec config patch`
   - `telec config validate`
2. CWD-independent config resolution via explicit root/path options.
3. YAML subtree read behavior for one or more requested root-anchored paths.
4. YAML patch behavior for one or more updates in a single operation.
5. Mandatory validation on every patch before write.
6. Atomic write semantics for successful patches.
7. Clear, actionable validation and parse errors.
8. Unit/integration test coverage for get/patch/validate behaviors.

### Out of scope

- Daemon hot-reload of config values after patch.
- New runtime config schema redesign.
- Replacing direct file edits everywhere in one pass.
- Editing `teleclaude.yml` (project/global/person job configs) in this todo.

## Functional Requirements

### FR1: `telec config get` returns root-anchored subtrees

- `telec config get` accepts zero or more dot-notation paths.
- If no path is provided, return the full config document.
- If one or more paths are provided, return only those subtrees.
- Returned payload must remain root-anchored (include top-level key hierarchy),
  not keyless scalar-only output.
- Missing paths must fail with explicit error messages listing unresolved paths.

### FR2: `telec config patch` applies YAML snippet patches

- `telec config patch` accepts YAML patch input (stdin and explicit input flag/file).
- Patch input is a subtree rooted at real config keys (no separate path argument required).
- Multiple key updates in one patch must be supported.
- Patch operation uses deterministic deep-merge semantics.
- Non-mapping top-level patch payloads are rejected with actionable errors.

### FR3: Validation is mandatory before persistence

- Every `telec config patch` call validates the fully merged config before write.
- If validation fails, no write occurs.
- `telec config validate` validates current config without mutation and exits non-zero
  on any error.

### FR4: CWD independence and explicit targeting

- Commands must run correctly from any current working directory.
- Config target resolution must support explicit project root (and/or explicit config path)
  so remote/agent calls are deterministic.
- Default behavior should remain ergonomic for repository-local invocation.

### FR5: Output ergonomics for AI consumers

- Command output supports structured formats suitable for tool calls
  (at minimum YAML; JSON optional but recommended).
- Success and failure output must be machine-parseable enough for agent loops.

## Non-functional Requirements

1. Atomic file updates (write temp file + replace) to avoid partial config writes.
2. No silent fallback on malformed input.
3. Error messages include failing field/path context.
4. Backward-compatible behavior for existing `telec` commands.

## Acceptance Criteria

1. `telec config get` can retrieve full config and specific subtree paths.
2. `telec config patch` applies multi-key YAML patch in one call.
3. Invalid patches fail validation and do not modify `config.yml`.
4. `telec config validate` reports valid/invalid status with proper exit codes.
5. Commands work from outside repo root when explicit project root/path is passed.
6. Tests cover happy paths and failure paths for get/patch/validate.
7. CLI usage/help documents the new config command family.

## Dependencies

- None.

## Constraints

- Follow existing `telec` CLI style and argument parsing approach in
  `teleclaude/cli/telec.py`.
- Reuse existing runtime config validation/parsing behavior as source of truth
  where possible; do not fork schema logic.

## Risks

- Current `teleclaude.config` loads at import time; careless reuse can create side effects.
- Merge semantics ambiguity (replace vs deep-merge) can surprise users if not specified.
- Invalid path handling can drift if get/patch path semantics are implemented inconsistently.
