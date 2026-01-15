---
description: Research 3rd-party documentation and update index---

You are now in **research mode**. Your goal is to collect, summarize, and index 3rd-party documentation.

Research Brief: "$ARGUMENTS"

## Step 1: Search for Information

Use `google_web_search` to find authoritative sources for the requested documentation.

```
google_web_search(query="...")
```

## Step 2: Fetch and Analyze

Use `web_fetch` to retrieve the content of the most relevant sources.
Extract the most important facts, configuration options, and schemas.

## Step 3: Summarize and Index

Use the `scripts/research_docs.py` script to create the markdown file and update the index.

**Parameters:**
- `--title`: Clear, descriptive title (e.g., "Library Name v2 API")
- `--filename`: URL-friendly filename (e.g., "library-name-v2.md")
- `--source`: Primary source URL
- `--content`: Concise markdown summary of the research findings

```bash
./scripts/research_docs.py \
  --title "..." \
  --filename "..." \
  --source "..." \
  --content "..."
```

## Step 4: Verify

1. Check `docs/3rd/index.md` to ensure the entry was added/updated correctly.
2. Read the generated file in `docs/3rd/` to verify quality.

# Acceptance Criteria

- Documentation is concise and focused on actionable facts.
- Index is up-to-date.
- Sources are linked.

