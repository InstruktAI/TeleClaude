---
description: Take a human's request for an MCP server from need to a working, correctly scoped declaration — machine-wide or project-local — with credentials referenced safely and the result verified.
activation_trigger: Use when a human asks to add, register, or declare an MCP server — machine-wide or for one project only — or when a task needs an MCP capability that no configured server provides.
delivered_by:
  - per-project-mcp-registry
---

# Declare MCP Server — Procedure

## Goal

Deliver a requested MCP server at the scope the need dictates: shared machine-wide infrastructure through the TeleClaude registry and lazy runtime, or a project-only integration through the project's own registry and generated agent-native project-local configs.

## Preconditions

- The need is concrete: which server (command or endpoint), and who should see it — every project on the machine, or exactly one project.
- For credentialed servers, the credential exists or can be provisioned; its value is never written into any registry or generated file.

## Steps

1. **Resolve scope from the need, never from where the conversation happens.**
   - A generic utility every project may use belongs in the machine-wide TeleClaude registry — the curated home of the global catalog, in the TeleClaude repository.
   - A project-specific or personal integration belongs in the owning project's registry files. Project declarations are visible only inside their project; there is no project-to-global promotion path — a server that outgrows its project graduates into the machine-wide registry instead.
2. **Author the declaration in the scope's registry file.**
   - Machine-wide: `teleclaude-mcp.jsonc` in the TeleClaude repository; machine-local overrides go in `teleclaude-mcp.local.jsonc` beside it.
   - Project-local: `teleclaude-mcp.jsonc` at the project checkout root; machine-local overrides go in `teleclaude-mcp.local.jsonc` beside it (gitignored — it never enters version control).
   - Both scopes use the TeleClaude wrapper shape with top-level `servers`. A project declaration carries the server-launch contract only — transport, command and arguments or URL and headers, environment references, enabled state. Machine-wide-runtime fields (native-publication opt-in, lazy-lease tuning, catalog trigger metadata) are invalid in a project registry and rejected with an error naming the field.
   - Credentials are always environment references such as `${VAR}` — never literal values, in either scope.
3. **Machine-wide scope: done at declaration.** The daemon's lazy runtime serves the server through `telec mcp list`, `list-tools`, and `call`; no generation step exists.
4. **Project scope: generate.** Run `telec sync` (or `telec projects init`) in the project. Generation writes the agent-native project-local MCP configs for each served CLI and provisions todo worktrees; outputs are machine-local and never committed.
5. **Act on every diagnosis the generation result names.** Generation is fail-closed and diagnostic, never silently corrective:
   - an environment name not eligible for agent pass-through, or absent → authorize the name in the agent environment allow-list (`env_allow_list` in TeleClaude configuration) and set its value through TeleClaude environment configuration; only new sessions receive it;
   - an identifier collision with a hand-authored native entry, a tracked native config target, or a higher-precedence shadowing entry → surface it to the human; generation never overwrites or mutates those surfaces;
   - an unserved CLI → expected for CLIs without a safe project MCP surface; nothing to fix.
6. **Verify in a new session at the target scope.** Machine-wide: `telec mcp list-tools <slug>` returns the tool catalog. Project-local: the CLI's own MCP surface inside that project shows the server, subject to that CLI's trust and approval gates.

## Outputs

- A declaration at the correct scope, generated project-local native configs when project-scoped, every generation diagnosis resolved or surfaced, and a verified working server in a new session.

## Recovery

- A registry error names the offending server and field; correct the declaration and rerun.
- A server failing at use time over a missing credential names the variable; authorize and set it, then start a new session.
- When a rule here needs its contract authority, the TeleClaude project's docs own it: from the TeleClaude project context, run a filtered `telec docs index --areas spec` and fetch the lazy-MCP-runtime feature spec.
