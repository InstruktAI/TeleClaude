# Scraper-to-Docs Pipeline Gap

## The Problem

The git-repo-scraper skill writes artifacts to `~/.teleclaude/git/github.com/{org}/{repo}/`
(index.md + history.md). The doc system reads from `~/.teleclaude/docs/third-party/`.
These two systems are completely disconnected.

Result: repos get cloned and indexed by the scraper, but `get_context` can never find
them because they're not in the doc system's namespace.

## Current State

- `vercel/ai` — cloned to `~/Workspace/public-repos/` but scraper artifact is EMPTY
  (directory exists at `~/.teleclaude/git/github.com/vercel/ai/` but no files)
- `openai/codex`, `Eriz1818/xCodex`, `thedotmack/memory-management-api` — properly indexed by
  scraper but NOT promoted to third-party docs

## What's Needed

Either:

1. A "promote" step in the scraper that converts index.md → third-party doc snippets
2. A bridge script that syncs scraper artifacts to the docs namespace
3. The scraper writes directly to `~/.teleclaude/docs/third-party/` instead

Also: the scraper index format (uses `@absolute-path` refs to public-repos) differs
from the doc snippet format (self-contained with frontmatter). These need reconciling.
