---
name: research
description: Explore a topic, gather information, and produce a durable, reusable record of findings.
---

@/Users/Morriz/.teleclaude/docs/general/reference/history-log.md

# Research

## Purpose

Orchestrate topic exploration by delegating to specialized skills and producing a durable record that links all findings together.

## Scope

- Produces a topic record under `~/.teleclaude/explore/<topic>/`.
- Delegates to specialized skills for specific source types.
- Links sub-skill artifacts via `@` references for reuse.
- Does NOT duplicate work that sub-skills already do.

**Skill routing:**

| Signal in request                                               | Skill to invoke       | Artifact location                          |
| --------------------------------------------------------------- | --------------------- | ------------------------------------------ |
| Git URL, repo name (owner/repo), "how does X repo work"         | `/git-repo-scraper`   | `~/.teleclaude/git/<host>/<owner>/<repo>/` |
| YouTube URL, channel name, "videos about X", transcript request | `/youtube`            | (ephemeral - capture in topic index)       |
| Library/framework name, "docs for X", official API reference    | `/tech-stack-docs`    | `~/.teleclaude/docs/third-party/<lib>/`    |
| General topic, comparison, "what is X", web sources             | Web search (built-in) | Capture in topic index                     |

**Routing rules:**

- If the request is ONLY about official library docs, recommend `/tech-stack-docs` and stop unless user confirms.
- If the request mentions a specific repo, invoke `/git-repo-scraper` first, then synthesize.
- If the request mentions YouTube content, invoke `/youtube` to fetch, then capture findings in the topic index.
- For mixed sources, invoke skills in sequence and aggregate in the topic index.

## Inputs

- Research brief (topic, question, or URLs).
- Optional: sources to prioritize or avoid.

## Outputs

- Topic index: `~/.teleclaude/explore/<topic>/index.md`
- Topic history: `~/.teleclaude/explore/<topic>/history.md`
- Links to sub-skill artifacts (not copies)

## Procedure

1. **Parse the brief** — Identify source types (repo? video? docs? general web?).

2. **Check existing work** — Read `~/.teleclaude/explore/<topic>/history.md` if it exists. Reuse prior answers for covered objectives.

3. **Delegate to specialized skills:**
   - **Git repo**: Invoke `/git-repo-scraper` with the repo reference. The skill produces `~/.teleclaude/git/<host>/<owner>/<repo>/index.md`. Link to it with `@~/.teleclaude/git/...`.
   - **YouTube**: Invoke `/youtube` with the query/channel. Capture the output in the topic index (YouTube doesn't persist artifacts).
   - **Library docs**: Recommend `/tech-stack-docs` and confirm before proceeding.
   - **Web sources**: Use web search directly and cite URLs.

4. **Aggregate in topic index** — Update `~/.teleclaude/explore/<topic>/index.md` with:
   - Brief summary of the objective
   - `@` references to sub-skill artifacts
   - Key findings synthesized from all sources
   - Gaps and open questions

5. **Log the answer** — Append to `history.md` using the history log format (timestamp, objective, answer, evidence, gaps).

6. **Respond** — Return the synthesized answer to the user.

## Examples

**Objective:** "Learn how anthropics/claude-code handles MCP connections."

1. Invoke `/git-repo-scraper` with `--host github.com --owner anthropics --repo claude-code`.
2. Wait for it to produce `~/.teleclaude/git/github.com/anthropics/claude-code/index.md`.
3. Read the index and search for MCP-related files.
4. Create `~/.teleclaude/explore/claude-code-mcp/index.md` with:
   - Link: `@~/.teleclaude/git/github.com/anthropics/claude-code/index.md`
   - Findings about MCP connection handling
5. Append answer to history.md.

**Objective:** "What are the latest AI agent videos from @aiexplained?"

1. Invoke `/youtube` with `--mode search --channels "@aiexplained" --query "AI agents" --period-days 30`.
2. Capture video titles, URLs, and transcript summaries in `~/.teleclaude/explore/aiexplained-agents/index.md`.
3. Append answer to history.md.

**Objective:** "Research Redis Streams for our message queue."

1. Detect this is library documentation — recommend `/tech-stack-docs` instead.
2. If user confirms general research, proceed with web search.
3. If user wants official docs captured, let `/tech-stack-docs` handle it.
