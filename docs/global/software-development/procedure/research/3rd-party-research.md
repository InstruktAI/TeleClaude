---
description:
  "Research third-party docs: search authoritative sources, fetch, summarize,
  and index findings."
id: software-development/procedure/research/3rd-party-research
scope: domain
type: procedure
---

# 3rd Party Research — Procedure

## Goal

Collect authoritative documentation, extract actionable facts, and store a concise summary as
internal documentation. Third-party documentation must never be referenced directly by agent
artifacts.

1. **Search**
   - Use authoritative sources. Acceptable sources are web links or Context7 snippet IDs.
   - Prefer primary docs and official vendor references.

2. **Fetch & Analyze**
   - Extract key facts, configuration, schemas, and constraints.
   - Separate facts from hypotheses. Do not publish hypotheses as facts.

3. **Summarize & Index**
   - Create a concise markdown summary as an internal snippet.
   - Add a **Sources** section listing web links or Context7 snippet IDs.
   - Update docs/index.yaml so the new entry is discoverable.

4. **Verify**
   - Read the summary for correctness and clarity.
   - Confirm the index entry is present and accurate.
   - If no valid sources were found, do not write a summary; report the gap instead.

- Summary is concise and actionable.
- Sources are listed under a **Sources** section as web links or Context7 snippet IDs.
- Index is updated.

## Preconditions

- The task has a clear research brief.
- At least one authoritative source is available (web link or Context7 snippet ID).

## Steps

- Identify sources (web or Context7) and record them.
- Draft an internal snippet that captures only validated facts.
- Add sources to a **Sources** section.
- Rebuild docs/index.yaml and validate.

## Outputs

- Internal documentation snippet with sources listed in **Sources**.

## Recovery

- If sources are missing or inconclusive, do not publish a snippet. Report the gap and
  request clarification or additional sources.
