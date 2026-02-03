---
name: stack-docs
description: Scrape and index official documentation for project dependencies using Firecrawl MCP tools. Use when the user asks to fetch docs for a library, framework, or tool in the tech stack. Outputs structured snippets under docs/third-party/.
---

# Stack Docs

## Purpose

Fetch, summarize, and index official documentation for project dependencies. Produces internal documentation snippets under `docs/third-party/` that are discoverable via `get_context`. Follows the 3rd-party-research procedure to ensure quality and traceability.

## Scope

- Targeted documentation scraping for libraries, frameworks, and tools used in the project.
- Output stored under `docs/third-party/{library}/` as documentation snippets.
- Snippets are registered in `docs/index.yaml` for discoverability.
- Budget-aware: Firecrawl free tier allows 1000 requests/month. Scrape only what is needed.

## Inputs

- A library or tool name (e.g., "Redis Streams", "FastAPI", "Textual").
- Optional: specific documentation pages or topics to focus on.
- Optional: path to `pyproject.toml` or `package.json` to auto-detect dependencies.

## Outputs

- Documentation snippet(s) under `docs/third-party/{library}/` following the snippet authoring schema.
- Each snippet includes a `Sources` section with the original URLs.
- Updated `docs/index.yaml` entry for discoverability.

## Procedure

**Available Firecrawl MCP tools:**

- `mcp__firecrawl-mcp__firecrawl_search` — Discover documentation URLs for a library.
- `mcp__firecrawl-mcp__firecrawl_scrape` — Scrape a specific documentation page as markdown.

**Single library workflow:**

1. Identify the library and the specific topic the user needs documented.
2. Use `firecrawl_search` to find the official documentation URL (e.g., "Redis Streams official documentation").
3. Scrape the documentation index/overview page with `firecrawl_scrape`.
4. If the topic spans multiple pages, selectively scrape only the relevant subsections (2-4 pages max).
5. Synthesize into a concise internal snippet following the snippet schema:

```markdown
---
description: { Brief summary of what this documents }
id: third-party/{library}/{topic}
scope: project
type: reference
---
```

Use H2 sections: `What it is`, `Canonical fields`, `Allowed values`, `Known caveats`, `Sources`.

6. Write to `docs/third-party/{library}/{topic}.md`.
7. Regenerate `docs/index.yaml` via tooling (do not edit manually).

**Stack scan workflow (bulk):**

1. Read `pyproject.toml` (Python) or `package.json` (Node) to enumerate dependencies.
2. For each key dependency, check if docs already exist under `docs/third-party/`.
3. For missing dependencies, run the single library workflow above.
4. Prioritize: core frameworks first, then frequently-used utilities, skip standard library and trivial packages.

**Quality rules:**

- Separate facts from hypotheses. Do not publish hypotheses as facts.
- If official docs are unavailable or inconclusive, report the gap instead of guessing.
- Keep snippets concise and actionable — extract configuration, API patterns, constraints, and gotchas.
- Always include a `Sources` section with the original URLs.
- Third-party docs must never be referenced directly by agent artifacts via `@` refs. They are internal reference material only.

## Examples

**Fetch docs for a specific library:**
User asks: "Get me the Redis Streams documentation."

1. `firecrawl_search` for "Redis Streams documentation site:redis.io"
2. `firecrawl_scrape` on the Redis Streams intro page
3. Scrape 1-2 additional pages (commands reference, consumer groups)
4. Write `docs/third-party/redis/streams.md` as a reference snippet
5. Regenerate index

**Scan the stack for missing docs:**
User asks: "Check what dependencies we're missing docs for."

1. Read `pyproject.toml` to list dependencies
2. Glob `docs/third-party/` to see what exists
3. Report gaps: "Missing docs for: textual, httpx, pydantic-settings"
4. Offer to fetch them one by one

**Focused topic within a library:**
User asks: "Get me the FastAPI dependency injection docs."

1. `firecrawl_search` for "FastAPI dependency injection documentation"
2. `firecrawl_scrape` on the relevant FastAPI docs page
3. Write `docs/third-party/fastapi/dependency-injection.md`
