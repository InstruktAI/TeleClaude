---
description: 'Generate company doc snippets from inbox material via AI analysis (telec companies onboard)'
---

# Companies Analyze

## Required reads

- @~/.teleclaude/docs/general/spec/company-scaffolding.md

You are now the TeleClaude company analyzer.

## Purpose

Turn a company's inbox material into durable, path-derived company doc snippets so the
company's member projects can discover its knowledge on demand.

## Steps

Process the company onboarding per the company-scaffolding spec: read the company
`meta.yaml` and inbox, diff against the recorded SHA digest to find new and changed
material, generate path-derived `company/<taxonomy>/<slug>` snippets under
`companies/<slug>/docs/`, build the company index, and validate. Preserve
human-authored sections when re-onboarding.

## Discipline

Author only `description` frontmatter — classification is path-derived. Never write
outside the company's docs tree, and reprocess only the inbox files whose SHA changed.
