---
name: research
description: Explore a topic, gather information, and produce a durable, reusable record of findings.
---

@/Users/Morriz/.teleclaude/docs/general/reference/history-log.md

# Research

## Purpose

Explore a topic, gather information, and produce a durable record of what was learned.

## Scope

- Produces a topic record that stays current as new requests arrive.
- Captures sources, findings, and gaps so work is not repeated.

## Inputs

- Research brief (topic, question, or URLs).
- Optional: sources to prioritize or avoid.

## Outputs

- Topic index: `~/.teleclaude/explore/<topic>/index.md`
- Topic history: `~/.teleclaude/explore/<topic>/history.md`
- Linked artifacts from the investigation

## Procedure

1. Create or open the topic folder under `~/.teleclaude/explore/<topic>/`.
2. Read `history.md` first and reuse prior answers if the request is already covered.
3. Identify the sources the request depends on. Use available tools:
   - `git-repo-scraper` — when the request depends on a Git repository.
   - `youtube` — when the request depends on YouTube videos or channels.
   - `tech-stack-docs` — when the request is explicitly about capturing official technical documentation (recommend using this instead and stop unless user confirms).
   - Web search — when the request depends on general web sources.
4. Gather information from the chosen sources and keep notes tied to the objective.
5. Update `index.md` to reflect the current understanding, with inline `@` references to any artifacts created or reused.
6. Formulate an answer that satisfies the objective.
7. Append that answer to `history.md` using the required history entry format.
8. Respond with the formulated answer.

## Examples

**Objective:** “Learn how repo x/y handles auth and summarize key files.”

- Process the repo and link any artifacts in the topic index with `@` references.
- Add the summary to topic history.
