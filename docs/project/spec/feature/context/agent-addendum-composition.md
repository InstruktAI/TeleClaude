---
id: 'project/spec/feature/context/agent-addendum-composition'
type: 'spec'
domain: 'software-development'
scope: 'project'
visibility: 'public'
description: 'Per-agent <AGENT>.addendum.md files are token-substituted and appended to each agent''s deployed AGENTS output under a literal \n---\n\n separator. No @-ref expansion; no AGENTS.addendum.md.'
---

# Agent Addendum Composition — Spec

## Required reads

- @docs/project/spec/domain/context.md

## What it is

Addendum composition is the per-agent decoration step that runs after baseline
inflation. For each target agent (`claude`, `codex`, `gemini`), the matching
addendum Source file `<AGENT>.upper().md` (`CLAUDE.addendum.md`,
`CODEX.addendum.md`, `GEMINI.addendum.md`) is read from the prefix root, run
through token substitution (`{AGENT_PREFIX}` / `{{agent}}`), and concatenated
onto the inflated baseline under a `\n---\n\n` separator. There is no
`AGENTS.addendum.md` support and no `@`-ref expansion on addendum content —
only token substitution.

Composition is a separate Sync step from inflation. Inflation builds the
baseline (and optionally runs inline-ref expansion on it); composition then
appends the agent-specific addendum verbatim after token substitution. The
result is the final Deployed `AGENTS.md` written under each project root for
each target agent.

## Canonical fields

### Use cases

```
Scenario: Claude addendum is appended after inflation with token substitution
  Given the prefix root contains a CLAUDE.addendum.md
  And the baseline AGENTS.md has been processed for the Claude target
  When the sync composition step runs for the Claude target
  Then CLAUDE.addendum.md is read from the prefix root
  And the substitution step substitutes {AGENT_PREFIX} and {{agent}} tokens for Claude's prefix
  And the substituted content is concatenated onto the baseline under a "\n---\n\n" separator
  And no @-ref expansion runs on the addendum content
```

```
Scenario: Missing addendum file is silently skipped
  Given the prefix root does not contain a GEMINI.addendum.md
  And the baseline AGENTS.md has been processed for the Gemini target
  When the sync composition step runs for the Gemini target
  Then no addendum block is appended to the output
  And no error is raised
  And the final Gemini output equals the inflated baseline alone
```

```
Scenario: AGENTS.addendum.md is not consulted
  Given the prefix root contains AGENTS.addendum.md but no per-agent addendum
  When the sync composition step runs for any target agent
  Then AGENTS.addendum.md is NOT read and NOT composed into any agent output
  And the final output for every agent equals the inflated baseline alone
```

```
Scenario: Codex local-phase repo override mirrors the addendum
  Given the current sync is in the local distribution phase with Codex repo-override enabled
  And the prefix root contains a CODEX.addendum.md
  When the Codex output is written
  Then the composed Codex AGENTS.md is written under the per-agent deployment directory
  And the same combined content is also written to AGENTS.override.md at the project root
```

### Cross-context references

- **agent_runtime** — Reads the Deployed `AGENTS.md` (baseline + addendum) at
  agent CLI startup. Addendum injection is invisible to the agent at runtime
  except through its observable behavior in the composed document.

## Known caveats

- Addendum filenames are derived as `<AGENT_NAME_UPPER>.addendum.md`, so only
  `CLAUDE.addendum.md`, `CODEX.addendum.md`, and `GEMINI.addendum.md` are
  consulted. There is no `AGENTS.addendum.md` support — files with that name
  are ignored even though the name looks plausible.
- Missing addendum files are NOT errors. The composition step treats absence
  as "no decoration", which is correct for projects that opt out, but means
  a typo in the filename is indistinguishable from an intentional opt-out.
- Composition is DISTINCT from inflation even though both write to the same
  Deployed file. The two are peer capabilities, not nested sub-steps. Master
  inflation builds the baseline; addendum composition decorates the baseline
  per agent. Mixing them would conflate two responsibilities that the context
  bounded context keeps separate for clarity.
- The `\n---\n\n` separator is a hardcoded literal. Consumers that parse the
  Deployed file looking for the boundary between baseline and addendum rely
  on this constant.
- Addendum content is NOT passed through inline-ref expansion. `@`-style
  refs inside an addendum will appear verbatim in the output. Only token
  substitution is applied. Operators authoring an addendum that wants inline
  expansion will not get it.
