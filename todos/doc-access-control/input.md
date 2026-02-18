# Role-Based Documentation Access Control

## Problem

When public-facing agents (help desk, onboarding bots) land in the system, they share the same documentation index as admin/ops agents. `get_context` returns all snippets regardless of who is asking. A help desk agent started for a stranger should never see admin operational docs, destructive procedures, or internal architecture details.

## Vision

Use front matter in doc snippets to declare clearance levels. The `get_context` tool filters results based on the calling agent's role/context.

## Requirements

### FR1: Snippet clearance levels

Each doc snippet gets a `clearance` front matter field:

- `public` — visible to all agents (help desk, onboarding, external)
- `internal` — visible to team member agents (contributor+)
- `admin` — visible to admin agents only

Default when omitted: `internal` (backward-compatible, nothing leaks by accident).

### FR2: Agent role propagation

When a session starts, the agent inherits a role from its launch context:

- Help desk sessions: `customer`
- Member-initiated sessions: `member`
- Direct admin sessions: `admin`

### FR3: get_context filtering

`teleclaude__get_context` must filter the snippet index by the caller's clearance level before returning results. A `public` agent never sees `internal`/`ops`/`admin` snippets in the index.

### FR4: Tool access gating

Config CLI subcommands (`telec config people`, `telec config env set`, etc.) should be restricted based on role. Public agents cannot modify config. This could be enforced via MCP tool filtering (existing policy) or CLI-level guards.

### FR5: Gradual migration

Existing snippets default to `internal`. New public-facing content is explicitly tagged `public`. Migration happens incrementally — no big-bang retagging.

## Success criteria

- A help desk agent started for an anonymous user sees only `public` snippets
- No snippet without explicit `clearance: public` is ever returned to a customer agent
- Config CLI commands reject unauthorized callers with a clear error
