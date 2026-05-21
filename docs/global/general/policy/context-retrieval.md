---
id: 'general/policy/context-retrieval'
type: 'policy'
scope: 'global'
visibility: 'public'
description: 'Guidelines for AI agents to retrieve relevant documentation snippets on demand.'
---

# Context Retrieval Policy — Policy

## Rules

- Use `telec docs` as the entry point for information discovery. **Always pass filters** —
  a bare `telec docs index` floods ~70KB into your context. Use
  `--areas <type>` and/or `--domains <domain>` and/or `--baseline-only` to scope the listing
  to what you actually need.
- Use it before any task where missing context could alter decisions.
- Use the three‑phase flow: filtered index first, then `telec docs get <id>` for selected IDs,
  then fetch any IDs listed in the `# Required reads (not loaded)` header of the previous response.
- Dependencies are NOT auto-expanded inline. The `# Required reads (not loaded)` header lists
  their IDs — fetch them explicitly with a follow-up `telec docs get` call if needed.
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

- If unsure about policies, procedures, roles, or constraints, run a filtered
  `telec docs index --areas <type>` (or `--baseline-only`) before editing or executing.

## Exceptions

- None.
