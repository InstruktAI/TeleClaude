# Role-Based Documentation Access Control

## Problem

When public-facing agents (help desk, onboarding bots) land in the system, they share the same documentation index as admin agents. `get_context` returns all snippets regardless of who is asking. A help desk agent started for a stranger should never see admin docs, destructive procedures, or internal architecture details.

## Vision

Use a `role` field in doc snippet frontmatter to declare the minimum role required to see the snippet. The `get_context` tool filters results based on the calling session's role.

## Requirements

### FR1: Snippet role levels

Each doc snippet gets a `role` frontmatter field:

- `public` — visible to all (help desk, onboarding, external)
- `member` — visible to team members and admin
- `admin` — visible to admin only

Default when omitted: `member` (nothing leaks by accident).

### FR2: Role propagation

When a session starts, the agent inherits the role of the person who triggered it:

- Help desk / unknown person: `public`
- Configured team member: `member`
- Admin: `admin`
- No role resolved: `public` (least privilege)

### FR3: get_context filtering

`teleclaude__get_context` filters the snippet index by comparing role ranks. A `public` session never sees `member` or `admin` snippets.

### FR4: Config CLI gating

Config CLI subcommands (`telec config people`, `telec config env set`, etc.) reject calls from `public` sessions. Clear error message.

### FR5: Gradual migration

Existing snippets default to `member`. New public-facing content is explicitly tagged `role: public`. No bulk retagging.

## Success criteria

- A help desk agent started for an unknown user sees only `role: public` snippets
- An admin sees everything
- No snippet without explicit `role: public` is ever returned to a public session
- Config CLI commands reject unauthorized callers with a clear error
