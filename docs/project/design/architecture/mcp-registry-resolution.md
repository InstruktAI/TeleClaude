---
description: How the effective MCP registry is resolved per invocation project — registry layering, project-context transport and validation, per-root daemon runtime keying, and the baked project MCP index.
delivered_by:
  - per-project-mcp-registry
---

# MCP Registry Resolution — Design

## Purpose

Resolve one effective MCP catalog per invocation context so a project's own registry declarations serve that project's sessions through the standard `telec mcp` surface, while every other context keeps the machine-wide catalog. The behavioral contract lives in `project/spec/feature/agent_runtime/lazy-mcp-runtime`; this design fixes the technical shape that realizes it.

## Inputs/Outputs

- **Inputs:** the machine-wide registry files at the TeleClaude repository root; a project's `teleclaude-mcp.jsonc` / `teleclaude-mcp.local.jsonc` at its checkout root; the invocation working directory; the registered-projects manifest (`PROJECTS_MANIFEST_PATH`); the caller identity already verified on `/mcp` routes.
- **Outputs:** the effective per-root catalog served by `telec mcp list` and the `/mcp` routes; per-root daemon runtimes with isolated leases, tool-catalog caches, and fingerprints; a baked project MCP index section in the declaring project's generated agent entrypoint files.

## Invariants

- Registry layering is fixed: machine-wide shared → machine-wide local → project shared → project local, deep-merged in that order by the existing loader merge. The loader stays parameterized by root; layering is composed by its callers.
- The daemon reads registry files only from the TeleClaude repository root and from roots listed in the registered-projects manifest. A caller-supplied root that is absent from the manifest resolves to the machine-wide catalog; arbitrary filesystem paths are never read.
- One runtime per resolved root, created lazily and held by the daemon; a lease, cached tool catalog, or fingerprint never serves another root. The machine-wide root remains the default for callers with no project context, preserving current outside-project behavior per subcommand.
- Environment placeholders resolve daemon-side at lease start from the TeleClaude environment, identically for both scopes; no secret enters a file or an agent session.
- `hidden: true` on a server entry affects only index-mode listing (the baked entrypoint indexes); runtime `telec mcp list`, tool listing, calls, launch, and fingerprints are unaffected by it.
- Project declarations never produce writes to user-home native agent configs; no publication path exists.

## Primary flows

- **CLI discovery (`telec mcp list`):** resolve the invocation project root via the existing invocation-position normalization (subdirectories and todo worktrees resolve to the owning checkout), compose machine-wide + project layers in-process, and print the effective catalog. Outside any project checkout, resolution fails exactly as it does today.
- **Tool listing and calls (`list-tools` / `call`):** the CLI sends its resolved invocation root with the request; the daemon validates it against the registered-projects manifest, resolves (or lazily creates) the runtime for that root, and serves the lease from that runtime. Requests carrying no root, or an unregistered one, are served by the machine-wide runtime — current behavior.
- **Config drift:** the existing per-runtime fingerprint and drift rules apply within each root; a changed project registry invalidates only that root's leases.
- **Baked project index:** the distribution step that generates a project's agent entrypoint files renders a project MCP index — the project's own declarations with activation triggers, minus `hidden` entries — by executing the listing in index mode from that project's root, through the same exec-directive mechanism that bakes the machine-wide index. A project with no registry declarations gains no section.
- **Schema:** the registry JSON schema gains the optional boolean `hidden` (default `false`) on server entries; both scopes use the identical schema.

## Failure modes

- **Unregistered or missing project root on an API call:** served machine-wide; the resolution decision is logged with the offered root. No error, no file read.
- **Project registry parse or contract error:** the existing registry error path fails the request naming the offending file and server; the machine-wide runtime is unaffected.
- **Registered-projects manifest unreadable:** all callers are served machine-wide and the condition is logged; no request fails on manifest absence.
- **Index bake failure for one project:** the distribution run reports the failing exec directive for that project; other projects and the machine-wide index are unaffected.
