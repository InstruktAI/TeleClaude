---
description: 'Guidelines for AI agents to retrieve relevant documentation snippets on demand.'
visibility: 'public'
---

# Context Retrieval Policy — Policy

## Rules

<!-- planned-change:remove-domain-baseline-session-injection -->
- **Read a domain's baseline bundle before substantive work in it when not yet loaded.** When a task enters a
  knowledge domain — e.g. writing or reviewing code/tests enters `software-development` —
  read that domain's bundle once at entry: `~/.teleclaude/docs/<domain>/domain-baseline.md`,
  but only if not yet loaded in this session. Bundles are large and certain agent run invocations
  target procedures that auto-inject those bundles upon session_start hook (i.e. `next-(prepare|work|build|review-*)` etc.).
  The bundle is the domain's full mandatory contract, pre-resolved to read in one pass; read
  it in full instead of piecemeal index browsing when starting fresh in a domain.
  Skip it only when the domain's contracts are already in context this session.
<!-- change:remove-domain-baseline-session-injection -->
- **Read a domain's baseline bundle before substantive work in it when not yet loaded.** When a task enters a
  knowledge domain — e.g. writing or reviewing code/tests enters `software-development` —
  read that domain's bundle once at entry: `~/.teleclaude/docs/<domain>/domain-baseline-bundle.md`,
  but only if not yet loaded in this session. A procedure that always needs the bundle names that generated
  bundle directly in its `## Required reads`; artifact transpilation expands the bundle into the procedure.
  The bundle is the domain's full mandatory contract, pre-resolved to read in one pass; read it in full instead
  of piecemeal index browsing when starting fresh in a domain. Skip it only when the domain's contracts are
  already in context this session.
<!-- /planned-change:remove-domain-baseline-session-injection -->
- Use `telec docs` as the entry point for information discovery. **Always pass filters** —
  a bare `telec docs index` floods ~70KB into your context. Use
  `--areas <type>` and/or `--domains <domain>` and/or `--baseline-only` to scope the listing
  to what you actually need.
- Use it before any task where missing context could alter decisions.
<!-- planned-change:required-reads-closure-guarantee -->
- Use the three‑phase flow: filtered index first, then `telec docs get <id>` for selected IDs,
  then fetch any IDs listed in the `# Required reads (not loaded)` header of the previous response.
- Dependencies are NOT auto-expanded inline. The `# Required reads (not loaded)` header lists
  their IDs — fetch them explicitly with a follow-up `telec docs get` call if needed.
<!-- change:required-reads-closure-guarantee -->
- Use the three‑phase flow: filtered index first, then `telec docs get <id>` for selected IDs,
  then fetch any IDs listed in the `# Required reads (not loaded)` header of the previous response.
- Dependencies are NOT auto-expanded inline by default. The `# Required reads (not loaded)`
  header lists their IDs — fetch them explicitly with a follow-up `telec docs get` call if
  needed.
- **Activatable procedures are fetched with `--closure`.** `telec docs get <id> --closure`
  resolves the full required-read closure and returns every body in one pass, each snippet
  exactly once, so nothing arrives as a pointer. Procedure catalogs direct agents to this
  form, and it is the mandatory form when activating a procedure from a catalog. Any caller
  may use it to receive a complete contract at the cost of a larger response.
<!-- /planned-change:required-reads-closure-guarantee -->
- **Third-party library docs: check consolidated docs first.** Before web searching or using
  Context7 for any library, framework, or tool, run `telec docs index --third-party` to check
  for existing coverage. If a consolidated snippet exists, use it. Web search and Context7 are
  fallbacks for gaps in coverage, not the starting point.

## Rationale

- Immediate context prevents drift from established policy, architecture, and procedure.
- Consolidated third-party docs are curated, verified, and project-aware. Live web results are
  noisy, may be outdated, and bypass the team's shared knowledge.

## Scope

- Applies to all agents, all projects, and all tasks.

## Enforcement

<!-- planned-change:remove-domain-baseline-session-injection -->
- Entering domain work without reading that domain's bundle
  (`~/.teleclaude/docs/<domain>/domain-baseline.md`), when its contracts are not already
  loaded, is a process miss — read the bundle first.
<!-- change:remove-domain-baseline-session-injection -->
- Entering domain work without reading that domain's bundle
  (`~/.teleclaude/docs/<domain>/domain-baseline-bundle.md`), when its contracts are not already
  loaded, is a process miss — read the bundle first.
<!-- /planned-change:remove-domain-baseline-session-injection -->
- If unsure about policies, procedures, roles, or constraints, run a filtered
  `telec docs index --areas <type>` (or `--baseline-only`) before editing or executing.

## Exceptions

- None.
