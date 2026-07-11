---
activation_trigger: 'FireCrawl web scraping - Use when asked or web search fails and you need to scrape JavaScript-rendered content'
description: 'Last-resort web scraping via Firecrawl MCP tools when built-in web search and consolidated docs are insufficient. JavaScript-rendered SPAs, structured data extraction, and multi-page crawling.'
visibility: 'public'
---

# Firecrawl Web Scraping — Procedure

## Goal

Scrape web content that built-in web search cannot reach — JavaScript-rendered SPAs, structured data behind client-side rendering, or multi-page site crawls. Each scrape costs one credit (1000/month free tier), so prefer consolidated docs and web search first.

## Preconditions

- Built-in web search and/or consolidated third-party docs have already been checked and found insufficient.

## Steps

1. **Confirm this is the right tool.** Check consolidated third-party docs first (`telec docs index --third-party`), then try built-in web search. Only use Firecrawl when those cannot reach the content (SPA, structured extraction, crawl).

2. **Choose the operation** based on intent:
   - **Single page scrape** — `firecrawl_scrape` with the target URL. Optionally pass `formats` (markdown, html, links, screenshot) and CSS selectors to include/exclude content.
   - **Site crawl** — `firecrawl_crawl` with root URL, optional `limit`, `maxDepth`, `includePaths`, `excludePaths`. Poll `firecrawl_check_crawl_status` with the returned crawl ID until complete.
   - **URL mapping** — `firecrawl_map` with the root URL to discover all indexed pages. Optionally pass a `search` term to filter.
   - **Structured extraction** — `firecrawl_extract` with one or more URLs and a JSON `schema` describing the fields to extract. The LLM parses pages and returns structured data.
   - **Autonomous research** — `firecrawl_agent` with the objective in `prompt`. Poll `firecrawl_agent_status` with the returned agent ID until complete.

3. **Invoke the selected operation** with `telec mcp call firecrawl <tool> --json '<payload>'`. Use `telec mcp list-tools firecrawl` first when the exact tool arguments are not already known.

4. **Process results** — extracted content arrives as markdown (scrape), page collections (crawl), URL lists (map), structured JSON (extract), or compiled findings (agent).

## Outputs

- **scrape**: Clean markdown content of the page.
- **crawl**: Collection of pages as markdown, delivered incrementally via status polling.
- **map**: List of discovered URLs.
- **extract**: Structured JSON data matching the provided schema.
- **agent**: Research findings compiled from multiple sources.

## Recovery

- If scraping fails, verify the URL is accessible and run `telec mcp list-tools firecrawl` to confirm the daemon can initialize the Firecrawl lease.

- If rate limited, wait and retry — free tier allows 1000 scrapes/month.
- If structured extraction returns incomplete data, refine the JSON schema or try scraping the page directly and extracting manually.
