# Requirements: Role-Based Documentation Access Control

## Problem

`teleclaude__get_context` returns all doc snippets to all agents regardless of the caller's role. When public-facing agents (help desk, onboarding bots) are introduced, they must not receive admin/ops/internal documentation. The current `audience` field and `human_role` session metadata provide the foundation — this work wires them together with a cleaner clearance hierarchy and extends coverage to tool gating.

## Background & Codebase Reality

The system already has:

- `Session.human_role` (`admin` | `customer` | `member` | null) stored in the DB.
- `audience` array field on snippets, parsed into `SnippetEntry.audience`.
- `_include_snippet()` in `context_selector.py` filtering snippets by `human_role → _allowed_audiences`.
- Current audience filter: `customer → {"public", "help-desk"}`, `member → {"admin", "member", "help-desk", "public"}`, `admin → None` (all).
- Default snippet `audience: ['admin']` — all existing snippets without explicit audience are admin-only.

**Gap:** The `audience` multi-array is expressive but requires snippet authors to know every role name. A hierarchical `clearance` single-value field is needed as a simpler authoring interface.

---

## Functional Requirements

### FR1: `clearance` frontmatter field on snippets

Add a `clearance` field to the snippet frontmatter schema. It is a single value representing the minimum required agent clearance to see the snippet.

Clearance hierarchy (most restrictive → least restrictive):

| `clearance` value | Visible to roles                     |
| ----------------- | ------------------------------------ |
| `admin`           | admin only                           |
| `internal`        | member + admin                       |
| `public`          | customer + member + admin (everyone) |

**Default when omitted:** `internal` — backward-compatible; no snippet is accidentally public-facing.

`clearance` and `audience` must coexist:

- When `clearance` is set and `audience` is not explicitly set, derive `audience` from the clearance hierarchy table above.
- When both are set, `audience` takes precedence (explicit overrides derived).
- When neither is set, default to `clearance: internal` (then derive `audience`).

### FR2: Role hierarchy

Three roles, no further subdivision needed:

| `human_role`   | `_allowed_audiences`                            |
| -------------- | ----------------------------------------------- |
| `admin` / null | None (no filter, sees everything)               |
| `member`       | `{"internal", "public", "help-desk", "member"}` |
| `customer`     | `{"public", "help-desk"}`                       |

### FR3: `get_context` clearance filtering

`teleclaude__get_context` must filter snippet index entries by the caller's session `human_role`. The existing Phase 1 index and Phase 2 content retrieval must both honor the derived `_allowed_audiences`.

- Phase 1: snippets whose derived `audience` does not intersect `_allowed_audiences` are excluded from the index.
- Phase 2: if a requested snippet ID is not allowed by the caller's role, return an empty or access-denied entry (do not silently return content).
- No snippet with `clearance: admin` must appear in a `customer` or `member` agent's index.

### FR4: Config CLI tool gating

Config-modifying CLI subcommands must reject calls from sessions whose `human_role` is `customer`. The guarded commands are those that mutate state: `telec config people`, `telec config env set`, and similar destructive config operations.

Enforcement mechanism: add role check at the CLI handler level (not MCP tool filtering, which is a separate layer). A `customer` session invoking a guarded command receives a clear error message: `"Permission denied: this operation requires member or higher clearance."`.

Read-only config commands (`telec config show`, status queries) are not gated.

### FR5: Gradual migration of existing snippets

Do not perform bulk retagging of existing snippets. Migration rules:

1. The new default `clearance: internal` means all existing snippets (no explicit `clearance`) are treated as `internal` — they remain invisible to `customer` agents, which is the safe default.
2. Snippet authors explicitly tag `public` only for content intended for help-desk/customer-facing agents.
3. Admin-only content (e.g., itsUP API credentials, destructive procedures) must be explicitly tagged `clearance: admin`.
4. The existing `audience` field on snippets that already have it must continue to be respected without change.

---

## Non-Functional Requirements

- No performance regression in `get_context` — clearance derivation happens at index build time (not at query time).
- Schema is backward-compatible: adding `clearance` to existing snippets is optional; omitting it defaults to `internal`.
- No new user-facing migration step required; `telec sync` picks up `clearance` fields automatically.

---

## Success Criteria

1. A `customer`-role session calling `teleclaude__get_context` only receives snippets tagged `clearance: public` (or equivalent `audience`).
2. An `admin`-role session receives all snippets (unchanged from current behavior).
3. A `member`-role session receives all snippets tagged `clearance: internal` or `clearance: public` (and any with matching explicit `audience`).
4. An existing snippet with no `clearance` field is treated as `clearance: internal` and is invisible to `customer` sessions.
5. `telec config people` invoked from a `customer` session returns a clear permission error.
6. `telec sync` correctly derives and stores `audience` from `clearance` in the index YAML.

---

## Out of Scope

- MCP tool-level filtering by role (separate policy layer, already partially handled by existing MCP connection management).
- Retroactive retagging of all existing snippets (FR5 explicitly defers this).
- UI for clearance management — all tagging is via frontmatter edits.
