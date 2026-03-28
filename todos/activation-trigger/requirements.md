# activation-trigger — Requirements

## Problem Statement

Skills were removed because they loaded all frontmatter into agent context without
most being used. Moving to docs-first killed recognition-level awareness — agents
can discover procedures via `telec docs index` but don't proactively know which
capabilities they can offer. Procedures that describe activatable capabilities
need a progressive disclosure mechanism that surfaces them in generated AGENTS.md
without loading full content.

Additionally, the validation pipeline maintains a `_warn()`/`_error()` distinction
that has no semantic value — all findings are errors that block `telec sync`. The
`--warn-only` flag controls leniency, not severity category. This dual-layer adds
surface area without benefit.

## Success Criteria

1. Procedures with `activation_trigger` appear in a dedicated "Activatable
   Procedures" section in generated AGENTS.md, separate from the baseline index.
2. The same procedures are automatically excluded from the progressive baseline
   index to prevent duplication.
3. Validation rejects `activation_trigger` on non-procedure snippet types.
4. The validation pipeline uses a single error severity — no warning/error
   distinction.
5. `--warn-only` continues to control whether validation findings block sync.
6. All existing tests pass after adaptation to the new model.
7. `telec sync --validate-only` passes with activation_trigger on procedures.
8. `telec sync` produces correct AGENTS.md output.

## Requirements

### R1: Unified validation severity

The resource validation pipeline must use a single severity level for all findings.

- All validation findings are errors.
- The module exposes a single collection function, a single retrieval function,
  and a single clear function for validation findings.
- The `--warn-only` flag on sync controls whether collected findings block the
  sync operation — it does not imply a separate severity category.
- All existing validation call sites that previously reported warnings must
  report errors instead. [inferred: mechanical rename, ~28 call sites in snippet
  validation confirmed by codebase exploration]

**Verification:** Unit tests for validation models confirm single-severity API.
Sync tests confirm `--warn-only` leniency behavior is preserved.

### R2: `activation_trigger` frontmatter field

Procedure snippets may declare an optional `activation_trigger` field in
frontmatter.

- The field value is a non-empty string describing when to activate the procedure
  (a one-line trigger description for agent consumption).
- Validation must reject `activation_trigger` on any snippet type other than
  `procedure`.
- Validation must reject `activation_trigger` values that are empty or non-string.

**Verification:** Validation tests confirm acceptance on procedures, rejection on
other types, and rejection of invalid values.

### R3: Activatable procedures section in generated AGENTS.md

The distribution pipeline must collect all procedures with `activation_trigger`
and render a dedicated section in generated AGENTS.md.

- The section is titled "Activatable Procedures" and appears after the baseline
  index block.
- Each entry shows the snippet ID and the activation trigger text, formatted as
  a compact list scannable by agents.
- The section includes a brief header explaining that agents should load the full
  procedure via `telec docs get <id>` before acting.
- Entries are sorted for deterministic output. [inferred: consistent ordering
  prevents diff churn across syncs]

**Verification:** `telec sync` produces AGENTS.md with the section. Content
matches the activation_trigger values from procedure frontmatter.

### R4: Automatic baseline exclusion

Procedures that declare `activation_trigger` must be automatically excluded from
the progressive baseline index rendering.

- The exclusion is based on the presence of `activation_trigger` in the
  procedure's frontmatter — not a hardcoded list.
- This prevents duplication between the baseline index and the activatable
  procedures section.

**Verification:** Generated AGENTS.md baseline index does not contain entries for
any procedure that has `activation_trigger`. Activatable procedures section
contains those entries instead.

### R5: Baseline progressive cleanup

Remove procedure references from the baseline-progressive manifest that will be
covered by the activatable procedures mechanism.

The following 6 procedure references must be removed:

- `agent-artifact-authoring`
- `doc-snippet-authoring`
- `peer-discussion`
- `memory-management`
- `brainstorming`
- `debugging`

[inferred: these 6 are the subset of the 11 target procedures that currently
appear in baseline-progressive.md, confirmed by codebase exploration]

**Verification:** baseline-progressive.md no longer contains references to these
6 procedures. The remaining references are unchanged.

### R6: Procedure activation annotations

Add `activation_trigger` to the following 11 procedures:

| Procedure                                                          | Activation trigger                                                                  |
| ------------------------------------------------------------------ | ----------------------------------------------------------------------------------- |
| `general/procedure/brainstorming`                                  | Use when the user wants to refine an idea before implementation                     |
| `software-development/procedure/debugging`                         | Use when you encounter a bug, test failure, or unexpected behavior                  |
| `general/procedure/peer-discussion`                                | Use when a complex topic would benefit from two agents covering it together         |
| `general/procedure/youtube-research`                               | Use when user needs YouTube video search, channel research, or transcripts          |
| `general/procedure/git-repo-ingestion`                             | Use when you need to analyze an external Git repository                             |
| `general/procedure/firecrawl-web-scraping`                         | Use when web search fails and you need to scrape JavaScript-rendered content        |
| `general/procedure/memory-management`                              | Use when you encounter a durable user preference, friction, or relationship context |
| `software-development/procedure/research/tech-stack-documentation` | Use when researching a library or framework not yet in consolidated docs            |
| `general/procedure/doc-snippet-authoring`                          | Use when creating or updating documentation snippets                                |
| `general/procedure/agent-artifact-authoring`                       | Use when creating or updating agent artifacts                                       |
| `software-development/procedure/research/third-party-research`     | Use when researching third-party documentation and consolidating findings           |

**Verification:** `telec sync --validate-only` accepts all 11 procedures.
Generated AGENTS.md activatable section lists all 11.

### R7: Skill-authoring procedure update

The skill-authoring procedure must be updated to reflect that `activation_trigger`
on procedures is now the primary awareness/discovery mechanism for agent
capabilities.

- Skills remain warranted only when they carry executable scripts.
- The procedure must explain that procedural knowledge uses `activation_trigger`
  for progressive disclosure, not skills.

**Verification:** Updated procedure is valid per snippet schema. The gate step
explicitly states that procedural capabilities use `activation_trigger` for
progressive disclosure rather than baseline index inclusion, and that skill
creation is gated exclusively on carrying executable scripts.

### R8: Skill-creator skill deletion

The `skill-creator` skill must be deleted. Its function is superseded by the
`activation_trigger` mechanism on the agent-artifact-authoring procedure and the
skill-authoring procedure's existing gate logic.

**Verification:** The skill directory no longer exists. `telec sync` succeeds
without it.

### R9: Schema documentation

The snippet-authoring-schema spec must document `activation_trigger` as an
optional frontmatter field available on procedure snippets.

**Verification:** Updated spec is valid per snippet schema. Field is documented
with type constraint (procedures only) and value constraint (non-empty string).

## Scope Notes

This work spans validation infrastructure, distribution pipeline, documentation
content, and a skill deletion. While touching many files, it follows two coherent
flows: (1) validation cleanup flowing through its consumers, and (2) the
activation_trigger field flowing through validation → distribution → docs. The
high detail level in the input reduces discovery risk. The draft phase should
assess whether a single session can deliver this atomically or whether splitting
is warranted based on estimated lines of change.

## Deferred / Out of Scope

- Adding `activation_trigger` to procedures beyond the 11 listed — future work
  as new activatable procedures are identified.
- Changing the `telec docs index` output to surface activation triggers — the
  current index already shows procedures; the trigger is an AGENTS.md concern.
