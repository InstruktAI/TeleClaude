---
description: How the effective MCP registry is resolved per invocation project — the config-owned resolver, project-context transport and validation, per-root daemon runtime pooling, and the baked MCP indexes.
delivered_by:
  - per-project-mcp-registry
---

# MCP Registry Resolution — Design

## Purpose

Resolve one effective MCP catalog per invocation context so a project's own registry declarations serve that project's sessions through the standard `telec mcp` surface, while every other context keeps the machine-wide catalog. The behavioral contract lives in `project/spec/feature/agent_runtime/lazy-mcp-runtime`; the registry file and schema contract lives in `project/spec/teleclaude-config`; this design fixes the technical shape that realizes both.

### Prior art & adopt-vs-build

- **Path-authority validation — adopted from platform precedent.** The registered-projects manifest plus the `teleclaude.yml` checkout marker are the platform's existing authority pattern for "which directories are projects" (`project_manifest`, `resolve_project_root` / `is_project_checkout`); this design consumes that contract rather than inventing a path allowlist. The alternative — trusting caller-supplied paths with ad-hoc checks — is rejected as an open filesystem-authority boundary.
- **Runtime pooling — adapted from the runtime's own lease pattern.** The daemon already runs a keyed pool with idle reaping one level down (slug-keyed MCP leases inside one runtime); the design extends the same shape one level up (root-keyed runtimes inside one manager), reusing the established reaper/shutdown traversal discipline visible in the daemon's existing session and lease lifecycle code. A per-project daemon process — the comparable isolation alternative — is rejected as incompatible with the single-daemon platform design and its shared identity/transport stack.
- **Scoped-config authority — consistent with vendor practice.** The consolidated third-party research for the supported agent CLIs (per-CLI `mcp-config` docs) documents the same model this design adopts: project-scoped MCP configuration gated by an explicit trust/registration boundary (Claude Code folder trust, Codex trusted projects). No external infrastructure is introduced; adopt-vs-build resolves to build-nothing-new — compose three existing platform mechanisms.

## Inputs/Outputs

- **Inputs:** the machine-wide registry files at the TeleClaude repository root; a project's `teleclaude-mcp.jsonc` / `teleclaude-mcp.local.jsonc` at its checkout root; the invocation working directory; the registered-projects manifest (`PROJECTS_MANIFEST_PATH`); the caller identity already verified on `/mcp` routes.
- **Outputs:** the effective per-scope catalog served by `telec mcp list` and the `/mcp` routes; per-root daemon runtimes with isolated leases, tool-catalog caches, and fingerprints; baked MCP index sections in generated agent entrypoint files.

## Invariants

- **One resolver owns layering.** Complete machine-plus-project resolution lives behind a single config-owned API — `load_effective_registry(project_root: Path | None)` — consumed identically by CLI discovery and the daemon. No caller composes layers itself. Layering inside the resolver is fixed: machine-wide shared → machine-wide local → project shared → project local, deep-merged by the existing merge semantics.
- **The project layer reads canonical files only.** `mcp.json` / `mcp.local.json` compatibility imports remain a machine-wide-root contract; for a project root the resolver reads exactly `teleclaude-mcp.jsonc` and `teleclaude-mcp.local.jsonc`. This is a recorded divergence from the reuse-the-loader hypothesis in the filed input: the current per-root loader consults compatibility inputs for any root it is given, which would admit unauthorized project input shapes.
- **Project context travels only when a project registry exists.** The CLI supplies project context on a request only when the resolved invocation root actually declares a project registry (a canonical registry file present at the root); a genuine checkout with no registry files sends no context and is served machine-wide exactly as today, registered or not. A request that does supply a root is validated fail-fast against the registered-projects manifest — the platform's existing closed authority set for project roots; an unlisted root is rejected with a caller-safe error, never silently downgraded to machine-wide authority.
- **One runtime per validated root, one pool owner.** A runtime manager owned by the daemon holds root→runtime state: runtimes are created lazily on first validated use, the reaper traverses every runtime's leases, and daemon shutdown closes every lease of every runtime. A lease, cached tool catalog, or fingerprint never serves another root. The machine-wide runtime is the pool's permanent default entry.
- Environment placeholders resolve daemon-side at lease start from the TeleClaude environment, identically for both scopes; no secret enters a file or an agent session.
- `hidden: true` on a server entry affects only index-mode listing; runtime `telec mcp list`, tool listing, calls, launch, and fingerprints are unaffected. Project declarations never produce writes to user-home native agent configs; no publication path exists.

## Primary flows

- **CLI discovery (`telec mcp list`):** resolve the invocation project root via the existing invocation-position normalization (subdirectories and todo worktrees resolve to the owning checkout) and call the resolver with it. Outside any project checkout, resolution fails exactly as it does today.
- **Project context on the API:** `tool_api_call` — the seam that already injects identity headers — adds `x-teleclaude-project-root` carrying the CLI-resolved canonical root; absent when no root resolves. Daemon-side, a route dependency beside `verify_caller` validates the header against the registered-projects manifest into a typed scope — the validated root, or machine-wide when the header is absent. Validation failure maps to a 400 with a caller-safe `invalid_project_context` error naming no filesystem detail. The `/mcp` routes consume only the typed scope and select the runtime from the pool with it.
- **Config drift:** the existing per-runtime fingerprint and drift rules apply within each root; a changed project registry invalidates only that root's leases.
- **Baked indexes ride the existing distribution paradigm.** The distribution step already renders per-project sections into generated agent entrypoints (project baseline index, activatable-procedure catalog) during `telec sync`; the MCP indexes are two more such internally rendered sections, produced from the resolver directly — machine-wide scope for globally deployed artifacts, the project's own declarations for that project's entrypoint — with `hidden` entries excluded at the bake. No new CLI surface exists for this; the runtime `telec mcp list` is unchanged. A project with no declarations renders no section. Scope is fixed by the rendering call, so no distribution run can leak one scope's entries into another's output.
- **Schema:** the registry JSON schema gains the optional boolean `hidden` (default `false`) on server entries; both scopes use the identical schema. The config-owned contract for project registry files and `hidden` is carried as a pending change on `project/spec/teleclaude-config`.

## Failure modes

- **Supplied project root not in the manifest:** the request fails with the caller-safe `invalid_project_context` error; nothing is read from the offered path; the decision is logged with the offered root. A declaring-but-unregistered checkout therefore receives an actionable error rather than silent machine-wide service; registration is the operator's remedy.
- **Project registry parse or contract error:** the existing registry error path fails the request naming the offending file and server; the machine-wide runtime is unaffected.
