---
description: Graphify (graphifyy) — tree-sitter AST knowledge graph of a codebase
  for AI agent context; CLI/MCP query surface and per-change blast-radius (affected)
  primitive.
---

# Graphify — Overview

## What it is

Graphify is an open-source tool that turns a folder of code (plus docs, PDFs,
images, videos) into a queryable **knowledge graph** so an AI coding assistant
queries a structured map of relationships instead of grepping/re-reading files.
Canonical project: `safishamsi/graphify` (YC S26, MIT). Official PyPI package is
**`graphifyy`** (double-y); the CLI binary is `graphify`. It installs as a
`/graphify` skill across many assistants (Claude Code, Codex, Cursor, Gemini
CLI, Copilot, Aider, Antigravity, etc.) and also runs standalone as a Python
library / headless CLI.

This is the AST-based code-graph "Graphify" the research brief targets — not a
similarly-named tool. Disambiguation:

- `graphify-rs` / `graphify-core` (crates.io, repo `TtTRz/graphify-rs`) — an
  **independent third-party Rust rewrite by a different author** (Rom Chung /
  TtTRz), _not_ an official port. It reuses the same
  `detect → extract → build → cluster → analyze → export` pipeline and emits a
  **compatible `graph.json`**, but is a follower that tracks the Python upstream.
  As of 2026-06: v0.8.0 (Python is 0.8.31), ~37 stars / ~408 downloads, solo
  maintainer, **`NOASSERTION` license** (unclear/non-standard — treat as a
  dependency risk). Notable extras over Python: PageRank, Tarjan SCC cycle
  detection, incremental re-clustering, native binary (no Python runtime).
  Caveat: its README comparison table makes claims about the Python version that
  are **inaccurate** (e.g. "regex only", "no MCP", "Louvain") — the Python
  project in fact uses tree-sitter, ships an MCP server, and uses Leiden.
- `Howell5/graphify-ts` — a third-party fork: TypeScript/Node, AST via
  tree-sitter WASM, 12 languages, "code navigation layer for AI agents."
- Unrelated older "Graphify" names (iOS charting libs, data-viz toys) are **not**
  this project.

**Which is leading:** the Python project (`safishamsi/graphify`) leads on every
maturity axis — adoption (~59k stars vs ~37), release cadence (daily; 147
releases), license clarity (MIT vs NOASSERTION), governance, and breadth of
assistant integrations — and carries the `affected` blast-radius primitive. The
Rust rewrite is technically interesting but a 2-month-old solo follower; the
`graph.json` format is portable between them, so the data artifact is not
locked to either runtime.

## How it builds the graph (pipeline)

`detect() → extract() → build_graph() → cluster() → analyze() → report() → export()`
(each stage a pure function over dicts/NetworkX graphs; outputs only under
`graphify-out/`).

- **AST extraction is deterministic and local** — code files are parsed with
  **tree-sitter** (no LLM, no network). It yields `{nodes, edges}` where each
  edge carries a `relation` (`calls`, `imports`, `imports_from`, `inherits`,
  `extends`, `implements`, `uses`, `references`, `re_exports`, …) and a
  **confidence** tag: `EXTRACTED` (explicit in source), `INFERRED` (deduced,
  e.g. call-graph 2nd pass), or `AMBIGUOUS` (flagged for review).
- **LLM semantic extraction** is used only for non-code (docs/PDFs/images/video),
  via a configured backend (Gemini, Kimi, Claude, OpenAI, DeepSeek, Bedrock, or
  local Ollama). Headless `graphify extract` needs the matching API key; the
  in-IDE `/graphify` skill reuses the IDE's model session (no extra key).
- **Clustering** uses the Leiden community-detection algorithm; **analyze**
  surfaces "god nodes" (highest-degree concepts) and surprising cross-module
  links.

## Supported languages

AST extraction ships ~33 tree-sitter grammars. The brief's targets are all
**supported today** (declared as `pyproject.toml` deps): **Python, TypeScript,
JavaScript, Go, Rust**, Java, C, C++, C#, Ruby, Kotlin, Scala, PHP, Swift, Lua,
Zig, PowerShell, Elixir, Julia, Verilog, Fortran, Bash, Groovy, plus SQL/JSON
and others. **Go and Rust are first-class now, not roadmap items.** The README
states no formal roadmap; new languages follow a documented "add an extractor"
recipe (tree-sitter grammar + `extract_<lang>` + suffix registration).

## Outputs

`graphify-out/` →

- `graph.json` — full queryable graph (node/edge schema below).
- `graph.html` — interactive browser visualization.
- `GRAPH_REPORT.md` — highlights: key concepts, god nodes, surprising
  connections, suggested questions.

Optional exports: Mermaid call-flow HTML (`graphify export callflow-html`),
Obsidian vault, Markdown wiki, SVG, GraphML (Gephi/yEd), Neo4j Cypher.

Node/edge schema (from `ARCHITECTURE.md`):

```json
{
  "nodes": [{ "id": "...", "label": "...", "source_file": "path", "source_location": "L42" }],
  "edges": [
    {
      "source": "id_a",
      "target": "id_b",
      "relation": "calls|imports|...",
      "confidence": "EXTRACTED|INFERRED|AMBIGUOUS"
    }
  ]
}
```

## API / CLI / integration model

- **Build:** `/graphify .` (in-IDE skill) or headless `graphify extract <path>
[--backend …] [--directed] [--force] [--code-only] [--no-gitignore] [--out DIR]`.
  `--code-only` indexes code via the local AST only (no API key, skipping
  doc/paper/image files); `--force` forces a full re-scan, bypassing the
  incremental manifest gate and the semantic cache; `--no-gitignore` honors only
  `.graphifyignore`. Incremental: `--watch` auto-syncs on file change.
- **Code-only refresh:** `graphify update <path> [--force] [--no-cluster]`
  re-extracts code files with no LLM involved. Here `--force` overwrites
  `graph.json` even when the rebuild yields fewer nodes — the case that arises
  whenever a refactor deletes code, since a graph carried forward across
  incremental updates otherwise retains nodes for symbols the source no longer
  defines.
- **Query (CLI):**
  - `graphify query "<question>"` — scoped natural-language subgraph answer
    (BFS by default, `--dfs`, `--budget <tokens>`). Avg ~1.7k tokens vs ~123k for
    naive full-corpus context (vendor's ~71× claim).
  - `graphify path "<src>" "<dst>"` — shortest relationship path between nodes.
  - `graphify affected "<node-or-label>" [--depth N] [--relation R] [--graph p]`
    — **per-change blast radius**: reverse-BFS over dependency edges to list
    nodes that depend on the seed (i.e. what a change to it can impact), each with
    `source_file:source_location`. Default depth 2; relations default to the
    dependency set (calls/imports/inherits/uses/…).
  - `graphify god-nodes [--top N] [--graph p] [--json]` — the most connected
    nodes, i.e. the architectural hubs.
  - `graphify explain`, `graphify benchmark` (corpus-vs-subgraph token report).
- **MCP server:** `python -m graphify.serve graphify-out/graph.json` exposes
  structured tools: `query_graph`, `get_node`, `get_neighbors`, `get_community`,
  `god_nodes`, `graph_stats`, `shortest_path`, plus PR tools `list_prs`,
  `get_pr_impact`, `triage_prs`. The server hot-reloads when `graph.json`
  changes. Install with the `[mcp]` extra (`uv tool install "graphifyy[mcp]"`).
- **Always-on guidance:** `graphify install` writes assistant config (and, on
  Claude Code / Gemini CLI, a pre-search hook) that nudges the agent to prefer
  `graphify query` over raw file reads/greps.
- **Scoping inputs:** `.graphifyignore` (gitignore syntax incl. `!` negation)
  excludes paths; `graphify extract <subpath>` graphs a subtree.

## Relevance to TeleClaude

TeleClaude adopts Graphify as the engine behind its codebase **Blueprint**. This
note stays scoped to Graphify-the-tool; the authoritative TeleClaude integration
design is owned by the project docs — read those, not this section, for how it is
actually wired:

- **Decision + seam:** `project/adr/0016-graphify-as-codebase-blueprint-engine`
- **Capability contract:** `software-development/spec/codebase-blueprint`
- **Generation trigger:** the integration design's "Blueprint regeneration"
- **Plan-time consumption:** the `plan-draft` procedure

In one line: `integration` runs the no-LLM `graphify update` at integrate-time →
`.teleclaude/blueprint/graph.json` + a `manifest.json` freshness sidecar; agents
consume it through the blast-radius command the capability contract above names
(no MCP). The
durable caveats remain Graphify's: edges are `EXTRACTED` (sound) vs
`INFERRED`/`AMBIGUOUS` (hints); `affected` is a static reverse-BFS, not semantic
impact; cross-language and non-source couplings are blind spots.

## Sources

- [safishamsi/graphify (GitHub, canonical repo — README + ARCHITECTURE.md, branch v8 @ 863f0c1)](https://github.com/safishamsi/graphify)
- [graphifyy on PyPI](https://pypi.org/project/graphifyy/)
- [Graphify official site](https://graphifylabs.ai/)
- [TtTRz/graphify-rs (independent third-party Rust rewrite; crate `graphify-rs`/`graphify-core`, NOASSERTION license)](https://github.com/TtTRz/graphify-rs)
- [Howell5/graphify-ts (TypeScript fork)](https://github.com/Howell5/graphify-ts)
