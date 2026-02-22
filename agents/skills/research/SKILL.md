---
name: research
description: Explore a topic, gather information, and produce a durable, reusable record of findings.
---

# Research

## Required reads

- @~/.teleclaude/docs/general/spec/history-log.md

## Purpose

Investigate a topic, gather information from multiple sources, and produce a durable record of findings that can be reused in future sessions.

## Scope

- General-purpose research for any topic or question.
- Uses web search, documentation, and any available information sources.
- Maintains a persistent record so the same research doesn't need to be repeated.
- Free form research topic records live under `~/.teleclaude/explore/<topic>/`.

**Related skills (for specialized tasks):**

If the user's request implies using one of these, use these specialized skills:

- `/git-repo-scraper` — Deep analysis of a specific Git repository that will be pulled in to a standard location for future reference
- `/youtube` — YouTube video search, history, transcripts
- `/tech-stack-docs` — Capturing official library/framework documentation

These skills produce their own artifacts. If you use them during research, link to their outputs rather than duplicating.
(Example: third party docs research resides under `~/.teleclaude/docs/third-party/<lib>/<topic>.md`.)

## Inputs

- Research brief: a question, topic, or area to investigate.
- Optional: specific sources to consult or avoid.

## Outputs

When free form research is done we produce two main artifacts:

- Topic index: `~/.teleclaude/explore/<topic>/index.md` — synthesized findings
- Topic history: `~/.teleclaude/explore/<topic>/history.md` — log of questions asked and answered

## Procedure

1. **Check existing work** — Read `~/.teleclaude/explore/<topic>/history.md` if it exists. If the question was already answered, return that answer or build on it.

2. **Investigate** — Use web search, read documentation, consult available sources. Follow leads. Gather evidence.

3. **Synthesize** — Distill findings into a clear answer. Note what's certain vs. uncertain.

4. **Record** — Update `index.md` with current understanding. Append to `history.md` with: timestamp, objective, answer, evidence (URLs/paths), gaps.

5. **Respond** — Return the answer to the user.

## Examples

**"What are the main differences between Redis Streams and Kafka for message queuing?"**

1. Search for comparisons, Redis Streams documentation, Kafka documentation.
2. Identify key differences: persistence model, consumer groups, scaling, ordering guarantees.
3. Synthesize into a comparison table or summary.
4. Record in `~/.teleclaude/explore/redis-streams-vs-kafka/`.

**"What's the current state of WebGPU browser support?"**

1. Search for WebGPU browser support, caniuse data, recent announcements.
2. Find current status for Chrome, Firefox, Safari, Edge.
3. Note any recent changes or upcoming milestones.
4. Record findings with dated sources.

**"I want to understand how the X repository handles authentication"**

1. Recognize this is deep repo analysis — suggest `/git-repo-scraper` for thorough indexing.
2. If user wants quick research instead, do targeted web search and surface-level analysis.
