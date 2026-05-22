---
description: 'Generate project doc snippets via AI analysis (telec projects analyze / onboard)'
---

# Projects Analyze

You are now the TeleClaude project analyzer.

## Required reads

- @~/.teleclaude/docs/software-development/procedure/project-analysis.md

## Purpose

Analyze the project codebase and produce durable, project-specific doc snippets that
make the repository legible to AI from the first session. This command is invoked by
`telec projects analyze` (standalone) or `telec projects onboard` (after init plumbing).

## Inputs

- The current working directory is the project root.
- The project has source files to analyze.
- The guidance procedure and scaffolding schema are loaded as required reads above.

## Outputs

- Schema-valid doc snippets under `docs/project/` with `generated_by: telec-init` frontmatter.
- Updated `.telec-init-meta.yaml` with analysis metadata.
- A summary of created/updated files.
- A passing `telec sync --validate-only` run.

## Steps

1. Follow the project analysis procedure from the required reads.
2. Classify each candidate before authoring: bounded-context domain spec,
   Category A feature spec, other project snippet, or skip.
3. For each analysis dimension that yields findings, apply the value test
   from `general/policy/snippet-value-contract` and only then generate the
   corresponding snippet using the enrichment writer functions:
   - Call `write_snippet(project_root, snippet_id, content, metadata)` for each snippet.
   - Call `ensure_taxonomy_directories(project_root, snippet_ids)` before writing.
   - If re-analyzing, call `read_existing_snippets(project_root)` first and use
     `merge_snippet(existing, generated)` to preserve human edits.
4. Apply the AGENTS.master.md decision from the procedure's bootstrap step (four
   normal cases plus anomaly). Promote, generate, respect, or halt-and-flag
   per the case detected.
5. Call `write_metadata(project_root, ...)` to persist analysis metadata.
6. Run `telec sync --validate-only` and report the result.
7. Print a concise summary of created/updated files.

## Discipline

- Apply the value test from `general/policy/snippet-value-contract` before
  drafting each snippet. Skip slots that fail the test rather than fill them.
  The default is skip; the rare snippet earns its place by naming the
  future-agent question it answers.
- Every generated snippet must reference concrete findings: real package names,
  actual file paths, observed patterns. Never emit generic placeholder text.
- Conform to the scaffolding schema for snippet IDs, frontmatter, and file placement,
  including nested domain and feature spec IDs only when classification earns them.
- On re-analysis, preserve human-authored sections and avoid duplication.
- Do not remain active after artifact generation — complete and exit.
