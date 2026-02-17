# Requirements: Role-Based Documentation Access Control

## Problem

`teleclaude__get_context` returns all doc snippets to all agents regardless of the caller's role. Public-facing agents must not receive admin or member documentation. The current `audience` field and `human_role` session metadata provide the foundation — this work wires them together with a 1:1 clearance-to-role mapping.

## Background & Codebase Reality

The system already has:

- `Session.human_role` (`admin` | `customer` | `member` | null) stored in the DB.
- `audience` array field on snippets, parsed into `SnippetEntry.audience`.
- `_include_snippet()` in `context_selector.py` filtering snippets by `human_role → _allowed_audiences`.

**Simplification:** Clearance values map 1:1 to roles. No abstract audience concepts (`internal`, `help-desk`). The clearance value IS the minimum role required.

Note: `customer` in the DB is treated as equivalent to `public` (rename is a separate migration).

---

## Functional Requirements

### FR1: `clearance` frontmatter field on snippets

Add a `clearance` field to the snippet frontmatter schema. It is a single value — the minimum role required to see the snippet.

Three clearance levels, 1:1 with roles:

| `clearance` value | Visible to roles              |
| ----------------- | ----------------------------- |
| `admin`           | admin only                    |
| `member`          | member + admin                |
| `public`          | public + member + admin (all) |

**Default when omitted:** `member` — backward-compatible; no snippet is accidentally public-facing.

`clearance` and `audience` coexist:

- When `clearance` is set and `audience` is not explicitly set, derive `audience` from the clearance table above.
- When both are set, `audience` takes precedence (explicit overrides derived).
- When neither is set, default to `clearance: member` (then derive `audience`).

### FR2: Role hierarchy

Three roles only: `admin`, `member`, `public` (stored as `customer` in DB until renamed).

| `human_role`        | `_allowed_audiences`   |
| ------------------- | ---------------------- |
| `admin` / null      | None (sees everything) |
| `member`            | `{"public", "member"}` |
| `customer`/`public` | `{"public"}`           |

### FR3: `get_context` clearance filtering

`teleclaude__get_context` must filter snippet index entries by the caller's session `human_role`. Both Phase 1 index and Phase 2 content retrieval must honor `_allowed_audiences`.

- Phase 1: snippets whose derived `audience` does not intersect `_allowed_audiences` are excluded from the index.
- Phase 2: if a requested snippet ID is not allowed by the caller's role, return an access-denied entry (do not silently return content).
- No snippet with `clearance: admin` must appear in a `public`/`customer` or `member` agent's index.

### FR4: Config CLI tool gating

Config-modifying CLI subcommands must reject calls from sessions whose `human_role` is `customer`/`public`. The guarded commands are those that mutate state: `telec config people`, `telec config env set`, and similar destructive config operations.

Enforcement: role check at the CLI handler level. A `customer`/`public` session invoking a guarded command receives: `"Permission denied: this operation requires member or higher clearance."`.

Read-only config commands (`telec config show`, status queries) are not gated.

### FR5: Gradual migration of existing snippets

Do not perform bulk retagging of existing snippets. Migration rules:

1. The new default `clearance: member` means all existing snippets (no explicit `clearance`) are treated as member-visible — they remain invisible to `public`/`customer` agents, which is the safe default.
2. Snippet authors explicitly tag `clearance: public` only for content intended for public-facing agents.
3. Admin-only content must be explicitly tagged `clearance: admin`.
4. The existing `audience` field on snippets that already have it continues to be respected.

---

## Non-Functional Requirements

- No performance regression in `get_context` — clearance derivation happens at index build time.
- Schema is backward-compatible: adding `clearance` is optional; omitting defaults to `member`.
- No new user-facing migration step required; `telec sync` picks up `clearance` fields automatically.

---

## Success Criteria

1. A `public`/`customer`-role session calling `teleclaude__get_context` only receives snippets tagged `clearance: public` (or equivalent `audience`).
2. An `admin`-role session receives all snippets (unchanged from current behavior).
3. A `member`-role session receives snippets tagged `clearance: member` or `clearance: public`.
4. An existing snippet with no `clearance` field is treated as `clearance: member` and is invisible to `public`/`customer` sessions.
5. `telec config people` invoked from a `customer`/`public` session returns a clear permission error.
6. `telec sync` correctly derives and stores `audience` from `clearance` in the index YAML.

---

## Out of Scope

- MCP tool-level filtering by role (separate policy layer).
- Retroactive retagging of all existing snippets (FR5 explicitly defers this).
- UI for clearance management — all tagging is via frontmatter edits.
- Renaming `customer` → `public` in DB schema (separate migration todo).
- Removing `newcomer` role from config schema (separate cleanup todo).
