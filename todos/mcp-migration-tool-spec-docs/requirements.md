# Requirements: mcp-migration-tool-spec-docs

## Goal

Write 24 tool spec doc snippets (one per tool, excluding the legacy
`mark_agent_unavailable` alias) organized in 6 taxonomy groups. Each spec
documents what the tool does, its parameters, and how to invoke it via `telec`
and raw curl.

## Scope

### In scope

- Create folder structure: `docs/project/spec/tools/{context,sessions,workflow,infrastructure,delivery,channels}/`
- Write 24 tool spec markdown files with proper frontmatter
- Each spec includes: description, parameter table, `telec` invocation, raw curl
  equivalent, response example, and notes
- Mark baseline tools with `baseline: true` in frontmatter
- Run `telec sync` to register in context index

### Out of scope

- `telec` subcommand implementation (separate todo, runs in parallel)
- Context-selection wiring (separate todo)
- Updating CLAUDE.md (separate todo)

## Success Criteria

- [ ] 24 tool spec files created across 6 directories
- [ ] All specs pass `telec sync --validate-only`
- [ ] All specs appear in `docs/index.yaml` after sync
- [ ] 6 specs marked as baseline (get-context, help, list-sessions,
      start-session, send-message, get-session-data)
- [ ] Each spec has: frontmatter, What it is, Parameters table, Invocation,
      Raw equivalent, Response, Notes

## Tool Inventory

| Group          | Tool               | Baseline |
| -------------- | ------------------ | -------- |
| context        | get-context        | yes      |
| context        | help               | yes      |
| sessions       | list-sessions      | yes      |
| sessions       | start-session      | yes      |
| sessions       | send-message       | yes      |
| sessions       | get-session-data   | yes      |
| sessions       | run-agent-command  | no       |
| sessions       | stop-notifications | no       |
| sessions       | end-session        | no       |
| workflow       | next-prepare       | no       |
| workflow       | next-work          | no       |
| workflow       | next-maintain      | no       |
| workflow       | mark-phase         | no       |
| workflow       | set-dependencies   | no       |
| infrastructure | list-computers     | no       |
| infrastructure | list-projects      | no       |
| infrastructure | deploy             | no       |
| infrastructure | mark-agent-status  | no       |
| delivery       | send-result        | no       |
| delivery       | send-file          | no       |
| delivery       | render-widget      | no       |
| delivery       | escalate           | no       |
| channels       | publish            | no       |
| channels       | channels-list      | no       |

## Constraints

- Must follow snippet authoring schema (frontmatter with id, type, scope, description)
- Specs go under `docs/project/spec/tools/` (project scope, not global)
- Parameter tables must match current MCP tool input schemas exactly
- Raw curl examples must use the daemon Unix socket path
