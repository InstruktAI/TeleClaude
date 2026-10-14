---
description: Process a company's onboarding inbox into its knowledge snippets per
  the company-scaffolding spec, reprocessing only what changed.
role: helper
dispatch:
  agent:
    - claude
    - codex
    - gemini
    - deepseek
  thinking_mode: slow
---

# Company Analysis — Procedure

## Required reads

- @~/.teleclaude/docs/general/spec/company-scaffolding.md

## Goal

Turn the material in a company's onboarding inbox into that company's
knowledge snippets, keeping what humans authored and reprocessing only inbox
files whose content changed.

## Preconditions

- The session runs in the company's home folder.
- The company's `meta.yaml` and inbox are readable.

## Steps

<!-- planned:role-scoped-cli-context -->

Retrieve the commands this assignment uses with `telec -h --expand-role` before
your first `telec` call; `telec <command> -h` details any single command.
<!-- /planned:role-scoped-cli-context -->

1. Read the company `meta.yaml` and inbox.
2. Diff the inbox against the recorded SHA digest to find new and changed
   material; reprocess only files whose SHA changed.
3. Generate snippets at `companies/<slug>/docs/local/<taxonomy>/<topic>.md`;
   their identities are path-derived. Preserve human-authored sections when
   re-onboarding.
4. Build the company index and validate.

## Outputs

- The company's knowledge snippets under its `docs/local` tree and its
  rebuilt index.

## Recovery

- A validation finding is fixed in the snippet it names and validation is
  rerun; nothing is written outside the company's `docs/local` tree.

## Discipline

Author only `description` frontmatter — classification is path-derived. Never
write outside the company's `docs/local` tree, and reprocess only the inbox
files whose SHA changed.
