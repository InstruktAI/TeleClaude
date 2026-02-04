---
name: git-repo-scraper
description: Ingest Git repositories for analysis. Keeps a durable index and history so future requests reuse prior work instead of redoing it.
---

@/Users/Morriz/.teleclaude/docs/general/reference/history-log.md

# Git Repo Scraper

## Purpose

Ingest a Git repository and produce durable artifacts that answer the current objective while preserving a reusable record of what the repository is and how it is organized.

## Scope

- Uses a helper script to clone or pull a repository into a checkout root.
- Scans the repo to produce an `index.md` that summarizes its identity, structure, key entry points, and agent files (if any).
- Detects changes since the last sync and uses them to refresh affected areas.
- Writes artifacts under `~/.teleclaude/git/<host>/<owner>/<repo>/`.
- Appends each request/response to `history.md` for reuse.

## Inputs

- Repo reference as **host + owner + repo** (preferred) or a full URL.
- Objective: what to learn or extract from the repo.

## Outputs

- Repo checkout: `~/Workspace/public-repos/<host>/<owner>/<repo>/` by default (override via `~/.teleclaude/config/teleclaude.yml` → `git.checkout_root`).
- Repo artifacts: `~/.teleclaude/git/<host>/<owner>/<repo>/index.md` and `history.md` (always).

## Procedure

1. Call the helper with either:
   - `~/.teleclaude/scripts/helpers/git_repo_helper.py --host <host> --owner <owner> --repo <repo>`
   - or `~/.teleclaude/scripts/helpers/git_repo_helper.py --url <repo_url>`
2. Read the JSON output for `repo_path` and `latest_changes` (one-line change summaries since the last sync).
3. Derive the artifact path from the repo reference as `<host>/<owner>/<repo>` (never from the checkout folder name). When given a URL, parse host/owner/repo from it.
4. Read `history.md` first and reuse prior answers if the objective is already covered.
5. When `latest_changes` is non-empty:
   - Scan the files implied by the change summaries (or related folders).
   - Re-check the entry points referenced in `index.md` (README/docs/examples).
   - Update any affected sections in `index.md` that depend on repo contents.
6. Ensure `index.md` contains these minimum sections:
   - Repo identity and structure
   - Key entry points (README, docs, examples)
   - Root agent file reference (if present)
   - Brief interpretation of how the repo is organized
7. Update `index.md` (preserve stable sections; refresh only what changed) and use inline `@` references for every file you cite.
8. **Agent file rule:** if a root agent file exists in the repo root (AGENTS.md, CLAUDE.md, GEMINI.md, CODEX.md, or agents.md), include exactly one inline `@` reference to it in `index.md`. Do not reference agent files not found in the repo root.
9. Formulate an answer that satisfies the objective, grounded in repo evidence.
10. Append that answer to `history.md` using the required history entry format.
11. Respond with the formulated answer.

## Examples

**Objective:** “Understand how repo x/y handles auth.”

- Call helper to clone/pull.
- Read README, agent file (if exists) and auth-related files.
- Update `index.md` with key pointers.
- Append an entry to `history.md` with the answer and evidence.
