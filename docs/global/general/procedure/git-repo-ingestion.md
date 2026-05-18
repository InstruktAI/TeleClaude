---
activation_trigger: 'Use when you need to analyze an external Git repository'
description: 'Ingest Git repositories for analysis. Clone or pull into a checkout root, produce durable index and history artifacts, and reuse prior work across requests.'
id: 'general/procedure/git-repo-ingestion'
scope: 'global'
type: 'procedure'
visibility: 'public'
---

# Git Repo Ingestion — Procedure

## Required reads

- @~/.teleclaude/docs/general/spec/history-log.md

## Goal

Ingest a Git repository and produce durable artifacts that answer the current objective while preserving a reusable record of what the repository is and how it is organized.

## Preconditions

- `~/.teleclaude/scripts/helpers/git_repo_helper.py` is available.
- Repo reference provided as host + owner + repo (preferred) or a full URL.
- An objective describing what to learn or extract from the repo.

## Steps

1. **Call the helper** with either:
   - `~/.teleclaude/scripts/helpers/git_repo_helper.py --host <host> --owner <owner> --repo <repo>`
   - or `~/.teleclaude/scripts/helpers/git_repo_helper.py --url <repo_url>`

2. **Read JSON output** for `repo_path` and `latest_changes` (one-line change summaries since the last sync).

3. **Derive the artifact path** from the repo reference as `<host>/<owner>/<repo>` (never from the checkout folder name). When given a URL, parse host/owner/repo from it.

4. **Check history first** — read `history.md` and reuse prior answers if the objective is already covered.

5. **Handle incremental changes** — when `latest_changes` is non-empty:
   - Scan the files implied by the change summaries (or related folders).
   - Re-check the entry points referenced in `index.md` (README/docs/examples).
   - Update any affected sections in `index.md` that depend on repo contents.

6. **Ensure `index.md` completeness** — minimum sections:
   - Repo identity and structure
   - Key entry points (README, docs, examples)
   - Root agent file reference (if present)
   - Brief interpretation of how the repo is organized

7. **Update `index.md`** — preserve stable sections; refresh only what changed. Use inline `@` references for every file cited.

8. **Agent file rule** — if a root agent file exists (AGENTS.md, CLAUDE.md, GEMINI.md, CODEX.md, or agents.md), include exactly one inline `@` reference to it in `index.md`. Do not reference agent files not found in the repo root.

9. **Formulate answer** that satisfies the objective, grounded in repo evidence.

10. **Append to history** using the required history entry format (see required reads).

11. **Respond** with the formulated answer.

## Outputs

- Repo checkout: `~/Workspace/public-repos/<host>/<owner>/<repo>/` by default (override via `teleclaude.yml` → `git.checkout_root`).
- Repo artifacts: `~/.teleclaude/git/<host>/<owner>/<repo>/index.md` and `history.md`.
- Answer delivered to the user.

## Recovery

- If the helper script fails to clone, verify network access and repo URL validity.
- If `history.md` is corrupted, delete it and rebuild from a fresh ingestion.
- If `index.md` sections are stale after multiple incremental syncs, regenerate from scratch.
