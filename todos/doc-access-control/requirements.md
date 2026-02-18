# Requirements: Role-Based Documentation Access Control

## Problem

`teleclaude__get_context` returns all doc snippets to all agents regardless of the caller's role. Public-facing agents must not receive admin or member documentation.

## Background

The system has `Session.human_role` in the DB. This feature adds a `role` frontmatter field to snippets and filters `get_context` results by comparing the caller's role against the snippet's required role.

Note: `customer` in the DB is treated as equivalent to `public` at runtime (DB rename is a separate migration).

---

## Functional Requirements

### FR1: `role` frontmatter field on snippets

Add a `role` field to snippet frontmatter. Single value — the minimum role required to see the snippet.

Three levels, hierarchical:

| `role` value | Visible to roles              |
| ------------ | ----------------------------- |
| `admin`      | admin only                    |
| `member`     | member + admin                |
| `public`     | public + member + admin (all) |

**Default when omitted:** `member` — no snippet is accidentally public-facing.

### FR2: Role hierarchy

Three roles: `admin`, `member`, `public`.

Rank comparison: `admin (2) > member (1) > public (0)`. A caller sees a snippet when their role rank >= the snippet's role rank.

### FR3: `get_context` role filtering

`teleclaude__get_context` filters snippet index entries by the caller's session role.

- Phase 1: snippets whose `role` rank exceeds the caller's role rank are excluded from the index.
- Phase 2: if a requested snippet ID is above the caller's role, return an access-denied entry (do not silently return content).
- No snippet with `role: admin` appears in a `public` or `member` session's index.

### FR4: Config CLI tool gating

Config-modifying CLI subcommands reject calls from sessions whose role is `public`/`customer`. Guarded commands: `telec config people`, `telec config env set`, and similar state-mutating operations.

Enforcement: role check at CLI handler level. A `public`/`customer` session receives: `"Permission denied. This operation requires member role or higher."`.

Read-only commands (`telec config show`, status queries) are not gated.

### FR5: Gradual migration of existing snippets

No bulk retagging. Migration rules:

1. Default `role: member` means existing snippets (no explicit `role`) are member-visible — invisible to `public` agents, which is the safe default.
2. Snippet authors explicitly tag `role: public` for public-facing content.
3. Admin-only content must be explicitly tagged `role: admin`.

---

## Non-Functional Requirements

- No performance regression in `get_context` — role comparison is a simple integer check.
- Schema is backward-compatible: `role` is optional; omitting defaults to `member`.
- No new user-facing migration step; `telec sync` picks up `role` fields automatically.

---

## Success Criteria

1. A `public`/`customer`-role session calling `teleclaude__get_context` only receives snippets tagged `role: public`.
2. An `admin`-role session receives all snippets (unchanged).
3. A `member`-role session receives snippets tagged `role: member` or `role: public`.
4. An existing snippet with no `role` field is treated as `role: member` and is invisible to `public` sessions.
5. `telec config people` invoked from a `public`/`customer` session returns a permission error.
6. `telec sync` stores `role` in the index YAML.

---

## Out of Scope

- MCP tool-level filtering by role (separate policy layer).
- Retroactive retagging of all existing snippets (FR5 explicitly defers this).
- UI for role management — all tagging is via frontmatter edits.
- Renaming `customer` → `public` in DB schema (separate migration todo).
- Renaming `human_role` → `role` on session model (separate refactor todo).
