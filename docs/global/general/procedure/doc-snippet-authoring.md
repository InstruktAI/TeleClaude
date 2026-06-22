---
activation_trigger: 'Use when creating or updating documentation snippets'
description: 'Author documentation snippets according to the taxonomy, schema and policies. Read this as soon as doc authoring is required, before writing any snippet.'
visibility: 'public'
---

# Snippet Authoring — Procedure

## Required reads

- @~/.teleclaude/docs/general/concept/documentation-snippets.md
- @~/.teleclaude/docs/general/policy/artifact-scope.md
- @~/.teleclaude/docs/general/principle/priming.md
- @~/.teleclaude/docs/general/principle/intent-first-documentation.md
- @~/.teleclaude/docs/software-development/principle/documentation-first-development.md
- @~/.teleclaude/docs/general/policy/referencing-doc-snippets.md
- @~/.teleclaude/docs/general/policy/snippet-value-contract.md
- @~/.teleclaude/docs/general/spec/snippet-authoring-schema.md

## Goal

Create a new snippet that conforms to schema and is discoverable by tooling.

## Preconditions

- Snippet taxonomy and schema references available.
- Target docs folder determined.

## Steps

0.  **Earn the snippet.** Before drafting, name the specific future-agent question this snippet answers and confirm it is not already answered by a one-minute source read, an already-loaded global policy or principle, the project's README, or an existing snippet. If you cannot name the question, or any of those already answers it, do not write the snippet — either skip it, or add a one-line entry under "See also" of an existing snippet pointing to the upstream source. Apply `general/policy/snippet-value-contract` rigorously: the default is **skip unless justified**, not "produce when applicable."
1.  Place the file at the correct path per the artifact-scope policy — the path determines `id`/`type`/`scope`/`domain` (the index build derives and materializes them; you do not author them).
2.  Author top-down: broader context should point to narrower details, not the other way around.
3.  Add frontmatter: `description` (required) and `visibility`; `id`/`type`/`scope`/`domain` are derived from the path and must NOT be authored. Classify `visibility` deliberately: `internal` is the default. Promote to `public` only when both conditions hold — (a) the snippet contains nothing sensitive (no credentials, no private infra, no non-public business intel, no personal data), and (b) the content is useful to anyone outside the project who asks the help desk about it. When in doubt, leave it `internal`.
4.  Write H1 title with correct type suffix.
5.  Add Required reads if the snippet depends on other snippets.
6.  Add all required sections for the taxonomy type.
7.  Organize content inside those valid sections. Use subordinate headings such as `###` when they improve readability; do not flatten useful structure just to avoid internal headings.
8.  If validation rejects a heading, first ask whether it should be downgraded under an existing schema section rather than deleted or flattened.
9.  After any doc change, run `telec sync` to deploy all artifacts. Commit the regenerated index files as part of the task — they are build outputs of the sync step and reflect the current truth of the docs directory.
10. Do not edit `docs/index.yaml` directly; `telec sync` regenerates it.
11. Avoid creating index.md files; only baseline.md manifests are allowed.
12. **Changing an existing snippet — bounded vs wholesale.** A live snippet is never overwritten in place to describe a change before it is delivered. Match the pending carrier to the shape of the change: bounded additions, replacements, and removals stay in body markers; wholesale reworks use a companion. The pending carrier names the delivering `<slug>`.

            - **Present-tense body (governs both forms).** Author the wrapped or companion body as the **future live contract**, in present tense, exactly as it must read once delivered. On delivery the marker lines vanish (ADD) or the companion replaces the parent (REPLACE) and the body stays **verbatim** — so it must already read as correct current-state contract with nothing stripped. The delivering `<slug>` lives **only** in the planned marker or the companion filename — **never in the body prose**. Do not write "Pending `<slug>`, …", "the new surface is …", "will", "is planned", or any history/rationale narration inside the body (see the Narration anti-pattern in `general/policy/snippet-value-contract`). DON'T: `Pending runner-dispatch, the manual-parking surface is: …`. DO: `The manual-parking surface is: …` — wrapped in `<!-- planned:runner-dispatch -->`, which is the only place the slug appears.
            - **Change-shape heuristic.** A bounded localized edit uses an in-body marker: `planned` for added content, `planned-change` for replacement or removal. A wholesale rewrite uses a companion file. ADRs do not use pending markers or companions; they land as immutable decision records.

    <!-- planned:host-scoped-pending-markers -->

            - **Marker tokens are host-scoped.** The slug a marker or `delivered_by` entry names is a token `<slug>@<host>` — the bare slug plus the computer that owns the in-flight todo. A bare token (no `@`) is local/legacy and resolves on the authoring machine. Stamp the local computer name when authoring a marker so other machines, whose local todo DB has no row for it, skip it instead of failing `telec sync`. The host suffix lives only in the marker/`delivered_by` token; the todo slug, CLI, and worktree/branch names stay bare.

    <!-- /planned:host-scoped-pending-markers -->

            - **Markers occupy their own line.** Every `planned`, `planned-change`, and `change` marker sits alone on its line — only whitespace before it and after it. Inline (mid-prose) markers are rejected by the validator at `telec sync`. To replace a clause inside a sentence, wrap the whole containing line or paragraph as the current/replacement spans rather than embedding markers in the prose; the rendered result is identical and the fold stays unambiguous.
            - **Markers never nest.** No marker may open inside another slug's open block — one in-body block contains only plain content between its own markers, never another `planned` / `planned-change` block. When a pending change targets a region a different slug already wraps in a pending marker, dependency-order the todos (`telec todo update B --after A`) so the later change authors against the earlier slug's delivered result — never nest the two in flight. This is the in-body counterpart of the companion **Ordering** rule. The validator rejects nested markers at `telec sync`.
            - **ADD** (new content: a new Gherkin scenario, a new rule, a new section). Author it **in context under its correct heading**, wrapped in a planned marker that names the slug:

              ```
              <!-- planned:<slug> -->
              ...the new content...
              <!-- /planned:<slug> -->
              ```

              Gherkin appends as more `#### UC-…` blocks; never reshuffle. On delivery the two marker lines are removed and the content stays exactly where it is, now live.

            - **CHANGE / REMOVE** (bounded replacement or localized removal). Author the current text and its replacement in place, wrapped in a planned-change marker that names the slug:

              ```
              <!-- planned-change:<slug> -->
              ...the current content...
              <!-- change:<slug> -->
              ...the replacement content...
              <!-- /planned-change:<slug> -->
              ```

              An empty replacement section is a localized removal. Default `telec docs get <id>` renders the current content with markers stripped. `telec docs get <id> --target <slug>` and delivery reconciliation render the replacement content with markers stripped.

            - **REPLACE** (a wholesale rework). Author a **companion file** `<stem>.<slug>.md` as a sibling of the parent `<stem>.md` — the **complete next version** of the parent, not a diff: a full snippet with the parent's authored frontmatter fields and a full body. The link is **the filename alone** — do **not** add any frontmatter field to the parent. The index derives a `(superseded by: <slug>)` suffix on the parent's line from the companion's existence, so reading the index shows a replacement is in flight; the companion itself never gets its own index line. On delivery the companion's content **replaces** the parent file and the companion is deleted (handled by the integration machine). The validator detects the companion by its sibling filename and validates it as a full snippet, exempting only id-collision checks because it deliberately derives the same id as the parent.

            - **Ordering.** Two pending companions on the same parent MUST be dependency-ordered (`telec todo update B --after A`) — never two independent reworks of one file in flight. Delivery is dependency-gated, so they merge-and-delete in order, each authored against the post-merge parent.

        - **Discoverability.** `telec docs index` flags pending work inline, never hiding it: `(delivered by: <slugs>)` on a brand-new snippet not yet live, `(superseded by: <slugs>)` on a live parent with a pending companion, planned section, or planned-change section (derived from the filename/marker). Companions never get their own line. The pending **bodies** stay invisible until active: default `telec docs get <id>` strips planned additions and renders the current side of planned-change blocks; `telec docs get <id> --target <slug>` reveals that slug's pending view. `telec docs index --target <slug>` narrows the listing to one todo's new snippets.

        - **Related-file discovery.** Before editing a live parent `<stem>.md`, list sibling files by stripping `.md` and globbing the stem (`ls docs/.../<stem>.*`). If a pending companion `<stem>.<slug>.md` exists, mirror the parent edit into that companion or coordinate ownership. A parent edit that leaves its pending companion unsynced is a defect.

13. **ADR discipline (decision capture).** Specs, procedures, and principles describe the _current state_; they hold no reasoning logs. An ADR is reserved for a real, contestable decision and the default is none — consult `general/policy/adr-discipline` for the bar before writing one.

## Outputs

- New or updated snippet with correct structure.
- `telec sync` run after changes.

## Recovery

- If `telec sync` fails, fix the issue and rerun it.
