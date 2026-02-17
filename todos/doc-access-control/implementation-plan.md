# Implementation Plan: Role-Based Documentation Access Control

## Overview

Extend the existing audience/clearance system with a `clearance` frontmatter field, update index building and `get_context` filtering, and add CLI-level gating for destructive config commands.

Three clearance levels: `public`, `internal` (default), `admin`.
Three roles: `admin`, `member`, `customer`.

All changes are backward-compatible. No bulk migration required. A single `telec sync` cycle picks up clearance values from snippets.

---

## Key Files

| File                             | Role                                                                |
| -------------------------------- | ------------------------------------------------------------------- |
| `teleclaude/docs_index.py`       | Index build: parse `clearance`, derive `audience`                   |
| `teleclaude/context_selector.py` | Phase 1/2 filtering: `_include_snippet()`, `build_context_output()` |
| `teleclaude/mcp/handlers.py`     | `teleclaude__get_context`: role resolution                          |
| `teleclaude/cli/`                | Config command handlers — add role guard                            |
| `docs/` + `~/.teleclaude/docs/`  | Example snippet with `clearance` field                              |

---

## [x] Task 1: `clearance` field support in `docs_index.py`

**File:** `teleclaude/docs_index.py`

### 1a. Clearance-to-audience mapping

Add a module-level constant for the clearance hierarchy:

```python
CLEARANCE_TO_AUDIENCE: dict[str, list[str]] = {
    "public":   ["public", "help-desk", "member", "internal", "admin"],
    "internal": ["member", "internal", "admin"],
    "admin":    ["admin"],
}
DEFAULT_CLEARANCE = "internal"
```

### 1b. Frontmatter parsing in `_parse_snippet_meta()` (or equivalent)

When building the index entry for a snippet:

1. Parse `clearance` from frontmatter (optional field).
2. Parse `audience` from frontmatter (optional array field).
3. Derive effective audience:
   - If `audience` is explicitly set → use as-is (explicit wins).
   - Else if `clearance` is set → lookup `CLEARANCE_TO_AUDIENCE[clearance]`.
   - Else → apply `DEFAULT_CLEARANCE` (`internal`) → `CLEARANCE_TO_AUDIENCE["internal"]`.
4. Store both `clearance` and effective `audience` in the `SnippetEntry`.

### 1c. Update `SnippetEntry` / `SnippetMeta` types

Add `clearance: str | None` field to `SnippetEntry`. This is informational in the index YAML but not required for runtime filtering (which uses the derived `audience`).

**Verification:** After `telec sync`, inspect `docs/project/index.yaml` — entries without explicit `clearance` must show derived `audience: [member, internal, admin]`.

---

## [x] Task 2: Update `context_selector.py` audience filter

**File:** `teleclaude/context_selector.py` — `build_context_output()`

Update the audience filter derivation block:

```python
if not human_role or human_role == "admin":
    _allowed_audiences = None
elif human_role == "member":
    _allowed_audiences = {"internal", "public", "help-desk", "member"}
elif human_role == "customer":
    _allowed_audiences = {"public", "help-desk"}
else:
    _allowed_audiences = None  # unknown role -> unrestricted (safe default for internal agents)
```

**Verification:** Add/update unit tests for each role mapping.

---

## [x] Task 3: Phase 2 access denial for forbidden snippets

**File:** `teleclaude/context_selector.py`

Currently, Phase 2 content retrieval does not re-check audience for explicitly requested `snippet_ids`. Add a guard:

1. After resolving requested snippet IDs to `SnippetMeta` objects, filter out any snippet that fails `_include_snippet()`.
2. For each filtered-out snippet, append a notice entry in the output:
   ```
   ---
   id: <snippet_id>
   access: denied
   reason: Insufficient clearance for current session role.
   ---
   ```
3. Do not silently omit — agents that explicitly request a snippet must receive a clear access denial, not empty content.

**Verification:** Confirm a `customer`-role session requesting an `admin`-clearance snippet receives the access-denied notice, not the content.

---

## [x] Task 4: CLI config command gating

**File:** `teleclaude/cli/` — find and update config command handlers

Target commands: any `telec config` subcommand that writes or deletes state (e.g., `people add`, `people remove`, `env set`, `env unset`).

Implementation:

1. At the start of each guarded command handler, resolve the current session's `human_role`.
2. If `human_role == "customer"`, exit with a non-zero code and print:
   ```
   Error: Permission denied. This operation requires member or higher clearance.
   ```
3. Read-only commands (`telec config show`, `telec status`, etc.) are not gated.

**Session identity in CLI context:** The CLI must know the current session ID to look up `human_role`. Check if `$TMPDIR/teleclaude_session_id` is available. If not in a session context, the role check is skipped (human terminal access, unrestricted).

**Verification:** Invoke a guarded command from a `customer` session and confirm the error. Invoke from an `admin` session and confirm it succeeds.

---

## [x] Task 5: Documentation and example tagging

1. Update the doc snippet authoring schema snippet (`general/spec/snippet-authoring-schema`) to document the `clearance` field and its valid values (`public`, `internal`, `admin`).
2. Tag at least one existing admin-only snippet with `clearance: admin` as a live example.
3. Update the authoring procedure snippet (`general/procedure/doc-snippet-authoring`) to mention `clearance` as the preferred field over direct `audience` for simple cases.

---

## Implementation Order

```
Task 1 (docs_index.py clearance parsing)
  → Task 2 (context_selector audience filter update)
    → Task 3 (Phase 2 access denial)
      → Task 5 (docs update + example tagging)
Task 4 (CLI gating) — independent, can run in parallel with Task 3
```

---

## Testing

| Scenario                                         | Expected                                                                       |
| ------------------------------------------------ | ------------------------------------------------------------------------------ |
| `customer` role Phase 1 index                    | Only snippets with effective `audience` containing `"public"` or `"help-desk"` |
| `member` role Phase 1 index                      | Snippets with `public`, `internal`, `member` audiences                         |
| `admin` role Phase 1 index                       | All snippets (unchanged)                                                       |
| Snippet with no `clearance`                      | Treated as `clearance: internal`, absent from `customer` index                 |
| Phase 2 request for forbidden snippet            | Access-denied notice returned, no content                                      |
| `telec config people` from `customer` session    | Permission denied error                                                        |
| `telec config people` from `admin` session       | Succeeds                                                                       |
| `telec sync` on snippet with `clearance: public` | `audience: [public, help-desk, member, internal, admin]` in index YAML         |

---

## Rollback

All changes are additive. The `clearance` field is optional. If a deployment fails:

- Revert `docs_index.py` and `context_selector.py`.
- The existing `audience` field on snippets is untouched and continues to drive filtering.
- No DB migration to undo.
