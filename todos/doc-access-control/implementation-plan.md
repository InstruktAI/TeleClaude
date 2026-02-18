# Implementation Plan: Role-Based Documentation Access Control

## Overview

Add a `role` frontmatter field to doc snippets, update index building and `get_context` filtering with a rank comparison, and add CLI-level gating for destructive config commands.

Three role levels: `public`, `member` (default), `admin`.
Hierarchy: `public (0) < member (1) < admin (2)`. Caller sees a snippet when their role rank >= the snippet's role rank.

All changes are backward-compatible. No bulk migration required. A single `telec sync` cycle picks up `role` fields from snippets.

---

## Key Files

| File                                | Purpose                                                      |
| ----------------------------------- | ------------------------------------------------------------ |
| `teleclaude/docs_index.py`          | Index build: parse `role`, store in index entry              |
| `teleclaude/context_selector.py`    | Phase 1/2 filtering: rank comparison in `_include_snippet()` |
| `teleclaude/mcp/handlers.py`        | `teleclaude__get_context`: role resolution from session      |
| `teleclaude/cli/config_cli.py`      | Config command handlers — role guard                         |
| `teleclaude/constants.py`           | `ROLE_VALUES` constant                                       |
| `teleclaude/resource_validation.py` | Snippet validation: validate `role` field values             |

---

## [x] Task 1: `role` field support in `docs_index.py`

- Add `ROLE_LEVELS`, `ROLE_RANK`, `DEFAULT_ROLE` constants
- Parse `role` from snippet frontmatter
- Store `role` in `SnippetEntry` (single string, not an array)
- Default to `member` when omitted

---

## [x] Task 2: Update `context_selector.py` role filter

- Replace `SnippetMeta.audience` with `SnippetMeta.role`
- Import `ROLE_RANK` from `docs_index`
- Resolve caller role: `human_role` from session, `customer` → `public`, `None`/unknown → `public` (least privilege)
- Filter: `caller_rank >= snippet_rank`

---

## [x] Task 3: Phase 2 access denial for forbidden snippets

- Phase 2 requests for snippets above the caller's role return an access-denied notice
- Not silently omitted — agents that request a snippet must receive a clear denial

---

## [x] Task 4: CLI config command gating

- Guard mutating config commands against `public`/`customer` role sessions
- Error message: "Permission denied. This operation requires member role or higher."
- Read-only commands are not gated
- If not in a session context (human terminal), role check is skipped

---

## [x] Task 5: Documentation and validation

- Update snippet validation (`resource_validation.py`) to validate `role` field values
- Add `ROLE_VALUES` to `constants.py`
- Update snippet authoring schema docs with `role` field

---

## Testing

| Scenario                                    | Expected                                 |
| ------------------------------------------- | ---------------------------------------- |
| `public`/`customer` role Phase 1 index      | Only `role: public` snippets             |
| `member` role Phase 1 index                 | `role: public` + `role: member` snippets |
| `admin` role Phase 1 index                  | All snippets                             |
| No role (None)                              | Treated as `public` — least privilege    |
| Snippet with no `role` field                | Treated as `role: member`                |
| Phase 2 request for forbidden snippet       | Access-denied notice, no content         |
| `telec config people` from `public` session | Permission denied error                  |
| `telec config people` from `admin` session  | Succeeds                                 |

---

## Rollback

All changes are additive. The `role` field is optional. If a deployment fails:

- Revert `docs_index.py` and `context_selector.py`
- No DB migration to undo
