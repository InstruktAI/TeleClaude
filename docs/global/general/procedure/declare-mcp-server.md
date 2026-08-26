---
description: Take a human's request for an MCP server from need to a working, correctly scoped declaration — machine-wide or project-local — served through the standard telec mcp surface.
activation_trigger: Use when a human asks to add, register, or declare an MCP server — machine-wide or for one project only — or when a task needs an MCP capability that no configured server provides.
delivered_by:
  - per-project-mcp-registry
---

# Declare MCP Server — Procedure

## Goal

Deliver a requested MCP server at the scope the need dictates. Both scopes serve through the same standard surface — the daemon's lazy runtime behind `telec mcp` — so every agent CLI is served identically: a machine-wide declaration reaches every project, a project declaration reaches only invocations from that project.

## Preconditions

- The requester and their role are known from the profile injected at session start; the invocation project sets the context. Both drive the routing below — as agent awareness, never as an enforcement gate.
- The need is concrete: which server (command or endpoint), and who should see it — every project on the machine, or exactly one project.
- For credentialed servers, the credential exists or can be provisioned; its value is never written into any registry file — declarations carry environment placeholders that the daemon resolves at lease start.

## Steps

1. **Resolve scope from the need, never from where the conversation happens.**
   - A generic utility every project may use belongs in the machine-wide TeleClaude registry — the curated home of the global catalog, in the TeleClaude repository.
   - A project-specific or personal integration belongs in the owning project's registry files. Project declarations are visible only to invocations from their project; there is no project-to-global promotion path — a server that outgrows its project graduates into the machine-wide registry instead.
   - When the request arrives in a side project and the need could be machine-wide, ask the human one direct question: should this server serve every project on this machine, or only this one?
2. **Route machine-wide declarations by who asks and from where.** The machine-wide registry is admin territory.
   - In the TeleClaude project, admin asking: author the declaration directly there — this is in-context work.
   - In a side project, admin asking: never write to the TeleClaude repository from this session. File a todo in the TeleClaude project instead (`telec todo create <slug> <content> --kind change --project-root <teleclaude-project-path>` with the requested declaration in the content); the TeleClaude lifecycle prepares and delivers it automatically, and admins have visibility of it there.
   - Requester is not an admin (member, contributor, customer): machine-wide registration is not theirs to file. Offer the project-local path instead — "I'll set this up for this project" — and continue with it.
3. **Author the declaration in the scope's registry file.**
   - Machine-wide: `teleclaude-mcp.jsonc` in the TeleClaude repository; machine-local overrides go in `teleclaude-mcp.local.jsonc` beside it.
   - Project-local: `teleclaude-mcp.jsonc` at the project checkout root; machine-local overrides go in `teleclaude-mcp.local.jsonc` beside it (gitignored — it never enters version control).
   - Both scopes use the TeleClaude wrapper shape with top-level `servers` and the same schema.
   - Credentials are always environment placeholders such as `${VAR}` — never literal values, in either scope. Provide the value through TeleClaude environment configuration; the daemon resolves it at lease start.
   - A declaration may set `hidden: true` to stay out of the baked agent-entrypoint indexes while remaining fully served and listed by the runtime `telec mcp list`.
4. **The declaration is live at once.** The daemon's lazy runtime serves both scopes through `telec mcp list`, `list-tools`, and `call` — from a project, the listing shows the machine-wide servers plus that project's own; from elsewhere, only the machine-wide catalog. A registry error fails fast naming the offending server and field.
5. **Refresh the project's baked index.** For a project declaration, run `telec sync` in the project so its generated agent entrypoint carries the project MCP index — the project's declared servers with their activation triggers — parallel to the machine-wide baked index.
6. **Verify from the target scope.** Run `telec mcp list` (the server appears with its trigger) and `telec mcp list-tools <slug>` (the daemon starts the lease and returns the tool catalog). For a project declaration, verify from inside that project — a subdirectory or todo worktree behaves the same.

## Outputs

- A scoped declaration served through the standard `telec mcp` surface, the project's baked MCP index refreshed when project-scoped, and a verified tool catalog.

## Recovery

- A registry error names the offending server and field; correct the declaration and rerun.
- A missing environment variable at lease start names the variable secret-safely; set it through TeleClaude environment configuration and retry.
- When a rule here needs its contract authority, the TeleClaude project's docs own it: from the TeleClaude project context, run a filtered `telec docs index --areas spec` and fetch the lazy-MCP-runtime feature spec.
