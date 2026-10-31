---
activation_trigger: 'Use when researching a library or framework not yet in consolidated docs'
description: 'Research and index official documentation for project dependencies as reusable internal snippets stored under ~/.teleclaude/docs/third-party/ or docs/third-party/.'
visibility: 'public'
---

# Tech Stack Documentation — Procedure

## Goal

Capture authoritative documentation for project dependencies and store concise internal snippets. Avoid re-researching what is already documented. Default to global storage so docs are reusable across projects.

## Preconditions

<!-- planned-change:third-party-docs-bypass-publication -->

- One upstream party is specified. An upstream party is one independently
  versioned project, product, protocol, library, framework, or tool with its
  own release lifecycle or governing source.
- At least one authoritative source is available or discoverable.
- Target scope is determined:
  - **Default**: `~/.teleclaude/docs/third-party/<upstream-party>/` (global, shared across projects).
  - **Project-only** (explicit user request): `docs/third-party/<upstream-party>/` within the current repo.

<!-- change:third-party-docs-bypass-publication -->

- One upstream party is specified. An upstream party is one independently
  versioned project, product, protocol, library, framework, or tool with its
  own release lifecycle or governing source.
- At least one authoritative source is available or discoverable.
- Target scope is determined:
  - **Default** (global, shared across projects): the mother project's
    `docs/third-party/<upstream-party>/`, committed there. Publication serves
    it from `~/.teleclaude/docs/third-party/<upstream-party>/`; never write
    into that deployed root. Working in another project, hand the content to
    a session in the mother project through the cross-project documentation
    route (`general/policy/documentation-discipline`).
  - **Project-only** (explicit user request): `docs/third-party/<upstream-party>/`
    within the current repo, in any project except the mother. The mother's
    `docs/third-party/` is published globally, so the mother has no
    project-only placement: a project-only request there is not written to
    global storage; report that no project-only placement exists and let the
    requester decide whether the finding is global.

<!-- /planned-change:third-party-docs-bypass-publication -->

## Steps

1. **Define the brief**
   - Clarify the exact upstream party and topic(s) to document and what will count as done.
   - If the brief names multiple upstream parties, split it into one brief per
     party before gathering or writing. Keep any comparison or adoption
     question in the relevant research or design artifact.
   - Check whether docs already exist:
     - Global: `~/.teleclaude/docs/third-party/index.yaml`
     - Project: `docs/third-party/index.yaml`
   - If docs exist and are current, return them instead of re-researching.

2. **Gather authoritative sources**
   - Prefer official docs and primary vendor references.
   - Use Context7, web search, or targeted scraping to fill gaps.
   - If official docs are thin, identify trusted secondary sources and note them.

3. **Extract and synthesize**
   - Capture configuration, API usage, constraints, and pitfalls.
   - Separate verified facts from assumptions. Do not publish assumptions as facts.
   - Keep platform-specific implications, recommendations, and comparisons out
     of third-party documentation. Record them in the platform's research or
     design authority and cite the party documents there.

4. **Write the snippet**
   - Follow the snippet schema: frontmatter, required sections, Sources, Gaps/Unknowns.
   - Keep content concise and actionable.
   - Include a **Sources** section with web links or Context7 snippet IDs.
   - If gaps remain, record them explicitly under **Gaps/Unknowns**.

5. **Stop**
   - Stop when the brief is satisfied and remaining gaps are explicitly recorded.

**Bulk workflow (stack scan):**

- Enumerate dependencies from `pyproject.toml` or `package.json`.
- Treat each independently versioned dependency as its own upstream party,
  including related projects that share an ecosystem.
- For each key party, check if docs already exist under `~/.teleclaude/docs/third-party/`.
- Fill only the missing high-impact dependencies first; skip trivial packages.
- Apply the parallel work principle: research independent parties simultaneously,
  but never consolidate their outputs into a shared third-party root.

## Outputs

- Documentation snippet(s) under the selected scope with Sources and Gaps/Unknowns sections.

## Recovery

- If no valid sources are found, do not write a snippet. Report the gap and request clarification or additional sources.
- If scope is unclear, default to global storage and state that choice explicitly.
- If factual upstream material and local architectural reasoning have already
  been mixed, split the verified facts by party first, move the local reasoning
  to its owning research or design artifact, and remove the mixed document.
