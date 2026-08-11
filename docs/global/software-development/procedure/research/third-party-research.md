---
activation_trigger: Use when entering unfamiliar third-party territory, or about to declare
  something impossible, require a fork, or invent a custom mechanism — scan prior
  art first (general/principle/grounding).
description: 'Research third-party docs: search authoritative sources, fetch, summarize,
  and index findings.'
visibility: public
---

# Third-Party Research — Procedure

## Goal

Collect authoritative documentation, extract actionable facts, and store a concise summary as
internal documentation. Third-party documentation must never be referenced directly by agent
artifacts.

This procedure also serves the **prior-art scan** the grounding principle requires before
designing unfamiliar infrastructure or concluding a hard problem is unsolved. When the scan
informs a single design or debugging decision, its findings are recorded in the relevant
artifact (the architecture Prior-art & adopt-vs-build section, or the debugging notes) rather
than a standalone snippet; publish a reusable snippet only when the research earns its place per
`general/policy/snippet-value-contract`.

1. **Search**
   - Use authoritative sources. Acceptable sources are web links or Context7 snippet IDs.
   - Prefer primary docs and official vendor references.

2. **Fetch & Analyze**
   - Extract key facts, configuration, schemas, and constraints.
   - Separate facts from hypotheses. Do not publish hypotheses as facts.

<!-- planned-change:state-validated-checkpoints-and-watcher-owned-deploy -->

3. **Summarize & Sync**
   - Create a concise markdown summary as an internal snippet.
   - Add a **Sources** section listing web links or Context7 snippet IDs.
   - After any doc change, run `telec sync`.

4. **Verify**
   - Read the summary for correctness and clarity.
   - Confirm the index entry is present and accurate.
   - If no valid sources were found, do not write a summary; report the gap instead.

<!-- change:state-validated-checkpoints-and-watcher-owned-deploy -->

3. **Summarize & Validate**
   - Create a concise markdown summary as an internal snippet.
   - Add a **Sources** section listing web links or Context7 snippet IDs.
   - After any doc change, run bare `telec sync` to validate the source.

4. **Verify**
   - Read the summary for correctness and clarity.
   - After source activity settles and the watcher publishes, confirm the index entry
     is present and accurate.
   - If no valid sources were found, do not write a summary; report the gap instead.

<!-- /planned-change:state-validated-checkpoints-and-watcher-owned-deploy -->

- Summary is concise and actionable.
- Sources are listed under a **Sources** section as web links or Context7 snippet IDs.

<!-- planned-change:state-validated-checkpoints-and-watcher-owned-deploy -->

- `telec sync` run after changes.

<!-- change:state-validated-checkpoints-and-watcher-owned-deploy -->

- Source validated with bare `telec sync`; publication verified after the watcher runs.

<!-- /planned-change:state-validated-checkpoints-and-watcher-owned-deploy -->

## Preconditions

- The task has a clear research brief.
- At least one authoritative source is available (web link or Context7 snippet ID).

## Steps

- Identify sources (web or Context7) and record them.
- Draft an internal snippet that captures only validated facts.

<!-- planned-change:state-validated-checkpoints-and-watcher-owned-deploy -->

- Run `telec sync`.

<!-- change:state-validated-checkpoints-and-watcher-owned-deploy -->

- Run bare `telec sync` to validate the source.

<!-- /planned-change:state-validated-checkpoints-and-watcher-owned-deploy -->

- Add sources to a **Sources** section.

## Outputs

- Internal documentation snippet with sources listed in **Sources**.

## Recovery

- If sources are missing or inconclusive, do not publish a snippet. Report the gap and
  request clarification or additional sources.
