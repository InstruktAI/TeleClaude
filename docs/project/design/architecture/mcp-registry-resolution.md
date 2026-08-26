---
description: How the effective MCP registry is resolved per invocation project — resolver layering, per-root daemon runtimes, and the baked MCP indexes.
delivered_by:
  - per-project-mcp-registry
---

# MCP Registry Resolution — Design

## Purpose

Resolve one effective MCP catalog per invocation context so a project's own registry declarations serve that project's invocations through the standard `telec mcp` surface, while every other context keeps the machine-wide catalog. The behavioral contract lives in `project/spec/feature/agent_runtime/lazy-mcp-runtime`; the registry file and schema contract lives in `project/spec/teleclaude-config`.

## Inputs/Outputs

- **Inputs:** the machine-wide registry files at the TeleClaude repository root; a project's `teleclaude-mcp.jsonc` / `teleclaude-mcp.local.jsonc` at its checkout root; the invocation working directory; the caller identity already verified on `/mcp` routes.
- **Outputs:** the effective per-scope catalog served by `telec mcp list` and the `/mcp` routes; per-root daemon runtimes with isolated leases, tool-catalog caches, and fingerprints; baked MCP index sections in generated agent entrypoint files.

## Invariants

- One config-owned resolver — `load_effective_registry(project_root: Path | None)` — owns all layering: machine-wide shared → machine-wide local → project shared → project local, deep-merged by the existing merge semantics. No consumer composes layers itself. The project layer reads only the canonical `teleclaude-mcp.jsonc` / `teleclaude-mcp.local.jsonc`; compatibility imports stay machine-wide-only. The TeleClaude Mother root is the canonical machine-wide scope — never overlaid on itself, always the pool's permanent machine-wide runtime.
- The CLI resolves the invocation project root (subdirectories and todo worktrees normalize to the owning checkout) and sends it with API requests; the daemon serves that scope after validating a canonical genuine TeleClaude checkout with a registry present, and rejects anything else caller-safe. One rule for every caller: the machine is a single trust domain — every same-machine caller is identity-verified and already holds filesystem access to every project, so scope selection grants nothing that access does not.
- One runtime per resolved root in a daemon-owned pool: created lazily, leases/catalogs/fingerprints never crossing roots, reaper and shutdown traversing every runtime. Environment placeholders resolve daemon-side at lease start from the TeleClaude environment, identically for both scopes.
- `hidden: true` affects only baked-index rendering; the runtime surface, launch, and fingerprints ignore it. Project declarations never reach user-home native agent configs; no publication path exists.

## Primary flows

- **CLI discovery (`telec mcp list`):** in-process resolution with the invocation-normalized root through the resolver contract; outside any project checkout it fails exactly as today.
- **API (`list-tools` / `call`):** requests carry the CLI-resolved root; a route dependency validates it and selects the runtime from the pool. Requests without a root are served machine-wide, as today.
- **Config drift:** the existing per-runtime fingerprint and drift rules apply within each root.
- **Baked indexes:** the `context` bounded context owns index publication; distribution renders it via the internal `@mcp-index` directive — machine-wide declarations for globally deployed artifacts, the project's own declarations for a project's entrypoint, `hidden` excluded. A project with no declarations renders no section. The global procedure's baked list uses `@mcp-index` (pending change on that procedure).
- **Schema:** server entries gain the optional boolean `hidden` (default `false`); both scopes share the identical schema.

## Failure modes

- **Supplied root fails checkout-or-registry validation:** caller-safe `invalid_project_context` rejection; nothing read from the offered path; logged path-free with the stable reason and caller identifiers.
- **Project registry parse or contract error:** the existing registry error path fails the request naming the offending file and server; the machine-wide runtime is unaffected.
