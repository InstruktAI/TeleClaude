---
activation_trigger: 'Use when creating or updating documentation snippets'
description: 'Author documentation snippets according to the taxonomy and schema.'
id: 'general/procedure/doc-snippet-authoring'
scope: 'global'
type: 'procedure'
visibility: 'public'
---

# Snippet Authoring — Procedure

## Required reads

- @~/.teleclaude/docs/general/concept/documentation-snippets.md
- @~/.teleclaude/docs/general/policy/artifact-scope.md
- @~/.teleclaude/docs/general/principle/priming.md
- @~/.teleclaude/docs/general/principle/intent-first-documentation.md
- @~/.teleclaude/docs/general/policy/referencing-doc-snippets.md
- @~/.teleclaude/docs/general/policy/snippet-value-contract.md
- @~/.teleclaude/docs/general/spec/snippet-authoring-schema.md

## Goal

Create a new snippet that conforms to schema and is discoverable by tooling.

## Preconditions

- Snippet taxonomy and schema references available.
- Target docs folder determined.

## Steps

0. **Earn the snippet.** Before drafting, name the specific future-agent question this snippet answers and confirm it is not already answered by a one-minute source read, an already-loaded global policy or principle, the project's README, or an existing snippet. If you cannot name the question, or any of those already answers it, do not write the snippet — either skip it, or add a one-line entry under "See also" of an existing snippet pointing to the upstream source. Apply `general/policy/snippet-value-contract` rigorously: the default is **skip unless justified**, not "produce when applicable."
1. Interpret the request through taxonomy: decide the correct type and scope per the artifact-scope policy.
2. Author top-down: broader context should point to narrower details, not the other way around.
3. Add frontmatter (id, type, scope, description, visibility). Classify `visibility` deliberately: `internal` is the default. Promote to `public` only when both conditions hold — (a) the snippet contains nothing sensitive (no credentials, no private infra, no non-public business intel, no personal data), and (b) the content is useful to anyone outside the project who asks the help desk about it. When in doubt, leave it `internal`.
4. Write H1 title with correct type suffix.
5. Add Required reads if the snippet depends on other snippets.
6. Add all required sections for the taxonomy type.
7. Organize content inside those valid sections. Use subordinate headings such as `###` when they improve readability; do not flatten useful structure just to avoid internal headings.
8. If validation rejects a heading, first ask whether it should be downgraded under an existing schema section rather than deleted or flattened.
9. After any doc change, run `telec sync` to deploy all artifacts. Commit the regenerated index files as part of the task — they are build outputs of the sync step and reflect the current truth of the docs directory.
10. Do not edit `docs/index.yaml` directly; `telec sync` regenerates it.
11. Avoid creating index.md files; only baseline.md manifests are allowed.
12. **Spec-diff companion sync (migration-window discipline).** If the snippet being edited is `type: spec` AND a sibling `<stem>-v2-diff.md` companion exists (file convention for `type: spec-diff` per `general/spec/snippet-authoring-schema`), the SAME operation also reviews the companion and updates it if your edit affects what the diff describes. The relationship is intelligence-managed — no lint enforces it. The same discipline applies when authoring a new `spec-diff`: read the parent spec first, write only the delta sections (Replaces / Adds / Removes / Why), do not duplicate parent content. See `software-development/principle/documentation-first-development` section 10 for the spec-diff companion infrastructure.
13. **ADR discipline (decision capture).** If your snippet change embeds a non-trivial decision — one a future agent might reasonably ask "why was it done this way?" about — author an accompanying ADR per `general/policy/adr-discipline`, following `general/procedure/adr-authoring`. Specs, procedures, and principles describe the _current state_; ADRs preserve the _reasoning_. Do not embed reasoning logs in primary artifacts.

## Outputs

- New or updated snippet with correct structure.
- `telec sync` run after changes.

## Recovery

- If `telec sync` fails, fix the issue and rerun it.
