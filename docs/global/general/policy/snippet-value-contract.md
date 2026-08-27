---
description: 'What earns a documentation snippet its place: the value test, anti-patterns that destroy signal, value-creating shapes, and a worked anti-example.'
visibility: 'public'
---

# Snippet Value Contract — Policy

## Required reads

- @~/.teleclaude/docs/general/concept/documentation-snippets.md
- @~/.teleclaude/docs/general/principle/intent-first-documentation.md
- @~/.teleclaude/docs/general/policy/referencing-doc-snippets.md
- @~/.teleclaude/docs/general/policy/artifact-scope.md

## Rules

### The value test

A snippet earns its place only if it changes future-agent behavior in at least
some session. Before drafting, the author must be able to:

1. Name the **specific future-agent question** this snippet answers.
2. Prove that question is **not already answered** by:
   - reading the relevant source in under a minute,
   - an already-loaded global policy or principle,
   - the project's README,
   - an existing snippet (which can be referenced instead of restated).

If the author cannot name the question, or any of the above already answers it,
the snippet does not earn its place. Either skip it, or add a one-line entry
under "See also" of an existing snippet pointing to the upstream source.

The default is **skip unless justified**, not "produce when applicable."

### Anti-patterns that kill value

- **Restatement.** Paraphrasing source code, configuration files, or workflow
  YAML. The artifact is the source of truth — point to it, do not duplicate it.
- **Value-copying.** Naming a runtime or configuration value's owner is useful;
  repeating the value is restatement with a shelf life. Numbers, durations,
  limits, thresholds, ports, paths, defaults, cadences, retention windows,
  current enum members, configured services, registry contents — anything whose
  canonical value lives in code, configuration, schema, or a runtime registry.
  The copy goes stale the moment the value moves, and a reader who finds two
  answers cannot tell which is authoritative. State purpose, invariants, and
  ownership; let the declaration carry the value.
- **Duplication.** Repeating content already present in a global snippet.
  Reference per `general/policy/referencing-doc-snippets`; do not restate.
- **Genericity.** Asserting things true of every repository in the same
  language or framework. The global language policy already covers it.
- **Coverage instinct.** Producing a snippet to fill a taxonomy slot rather
  than to capture intent. The discovery-to-taxonomy table is a list of
  shapes worth considering, not a checklist to complete.
- **Narration (log-in-the-doc).** A snippet body that records _how it got
  here_ or _what is coming_ instead of stating _what is_. A body states
  present-tense intent and contract — nothing else. Each form of narration
  has a proper home, and the body is never it:
  - **History** ("replaces the v1 path", "is retired", "used to produce
    misleading rows", "previously named X") → git. The body describes the
    current contract; the prior contract is in the history. A version or
    revision marker inside a contract is history in this sense however it is
    spelled — an edit count in a heading, a note recording what an earlier
    version said. The test is derivability: a document states what is true
    now, so re-deriving it from current reality must yield the same bytes, and
    an edit count is derivable only from the past.
  - **Rationale** ("because X", "this avoids Y", "the reason we chose this")
    → the snippet's own Rationale section where its type has one; otherwise it
    is dropped. The body states the contract, not the why. An ADR captures the
    why only for a real, contestable decision per `general/policy/adr-discipline`,
    and is pointed to from `## See Also` — never named inline in the body.
  - **Pending status and provenance** ("Pending `<slug>`, …", "(delivered_by
    `<slug>`)", "this opt-in is pending") → the `delivered_by` **frontmatter**
    field, never inline body prose. The delivering slug is coordination
    metadata; it never appears in the body. A pending snippet's body reads as
    present-tense contract — `delivered_by` is the only thing that says "not
    yet" (`software-development/principle/documentation-first-development`).
  - **Future framing** ("will", "is planned", "the new surface is going to")
    → present-tense description of the intended shape. Forward design is
    written as contract, not as forecast.

### What creates value

- **Durable intent the code can't express.** Why a constraint exists, what it
  defends against, what trade-off it embodies.
- **Non-obvious gotchas.** Behavior that would cost a future agent a wrong
  path if undocumented.
- **Live tech debt and drift.** State that lives outside any single file —
  known divergences between intent and implementation, deprecation phases.
- **Reverse pointers.** When this repository _implements_ a global policy,
  the project snippet points back to the global ID rather than duplicating
  the contract. This is the highest-value shape for projects that exist
  _because of_ a global standard.

### Worked anti-example

Seven snippets generated by `/telec-init-analyze` against the
`instruktai-python-logger` repository (2026-05-06). Each failed the value test
in a distinct way; together they cover every anti-pattern named above. Each
entry below is self-contained and survives deletion of the source files.

- **`project/design/architecture`** — Skeleton mostly correct, but the
  "Inputs/Outputs" section restated the public logging contract that already
  lives in `software-development/policy/python/logging`. Net new signal
  ≈ 20%. Anti-pattern: **Duplication** (the global policy already answers it).
  Correct shape: a one-line reverse pointer to the global policy plus any
  project-specific layering, if any exists.
- **`project/design/test-strategy`** — Described `pytest` + `tmp_path` +
  `monkeypatch` usage. Every Python repository tests this way. Anti-pattern:
  **Genericity**. Correct outcome: skip the snippet. The language's testing
  policy answers it.
- **`project/policy/conventions`** — Restated `software-development/policy/python/core`,
  `software-development/policy/python/tooling`, and `[tool.ruff]` from
  `pyproject.toml`. Anti-pattern: **Restatement** + **Duplication**.
  Correct outcome: skip; the global Python policies and the source
  configuration both answer it.
- **`project/spec/dependencies`** — Restated `pyproject.toml`'s
  `[build-system]` and `[project] dependencies`. Anti-pattern:
  **Restatement**. The `pyproject.toml` is the source of truth. Correct
  outcome: skip, or write a one-liner only if a dependency choice encodes
  durable intent the manifest cannot express.
- **`project/spec/entry-points`** — Restated `[project.scripts]` and `__all__`,
  both 30-second source reads. Anti-pattern: **Restatement**. Correct
  outcome: skip unless an entry point has non-obvious wiring (conditional
  registration, side-effect imports) that the source does not make explicit.
- **`project/spec/build-deploy`** — Paraphrased the GitHub Actions workflow
  YAML. Anti-pattern: **Restatement**. The YAML is the source of truth.
  Correct outcome: skip, or write a snippet only if the pipeline encodes
  constraints invisible in the YAML (why a step exists, what failure mode
  it defends).
- **`project/spec/configuration`** — Restated the per-app environment-variable
  contract that lives in `software-development/policy/python/logging`. This
  is the most catastrophic case in the set: **the project IS the
  implementation of the global policy**, and the snippet duplicated the
  contract instead of pointing back. Anti-pattern: **Duplication** of a
  global policy by its own implementing project. Correct shape: a
  reverse-pointer snippet — `See also: software-development/policy/python/logging`
  — plus any project-local extension if one exists. This is the canonical
  example of why the **Reverse pointers** value-creator exists.

Net signal across the set: ≈ 20%. After applying the value test, six of the
seven would have been skipped, and the seventh (`spec/configuration`) would
have collapsed into a reverse pointer.

## Rationale

Documentation snippets exist to deliver high-signal context selectively to
agents whose context windows are finite. A snippet that restates source,
duplicates a global policy, or paraphrases a config file consumes context
budget without changing behavior. The cost is ambient: every session that
loads it pays. The proprioception principle — _"if a cue does not change
behavior in at least some sessions, it does not belong"_ — applies as much
to on-demand snippets as to ambient signals.

The value contract operationalizes intent-first documentation by forcing
the author to name the intent before drafting. Without this gate, authoring
defaults to coverage — filling taxonomy slots because the table exists.
With this gate, authoring defaults to skipping, and each surviving snippet
carries durable signal.

## Scope

Applies to all snippet authoring contexts:

- Manual snippet authoring via `general/procedure/doc-snippet-authoring`.
- Automated authoring during `/projects-analyze` via
  `software-development/procedure/project-analysis`.
- Future authoring flows (company onboarding, scaffolding, manual updates).

The contract is procedural, not structural. It is enforced by the author
applying it before drafting and by reviewers applying it during review.
There is no automated grader — code that judges free-text snippet quality
would violate `software-development/principle/intelligence-boundaries`.

## Enforcement

- `general/procedure/doc-snippet-authoring` Required-reads this policy and
  installs Step 0 ("Earn the snippet") before taxonomy interpretation.
- `software-development/procedure/project-analysis` Required-reads
  `doc-snippet-authoring`, transitively inheriting this policy.
- Reviewers apply the value test during snippet review. A snippet that
  fails the test is rejected; the reviewer either skips it or replaces it
  with a reference under "See also" of an upstream source.
- The discovery-to-taxonomy tables in `project-analysis` and
  `init-scaffolding` describe shapes worth considering, not slots to fill.
  Each row is conditional on the value test.

## Exceptions

None. If the value test cannot be satisfied, the snippet is not authored.
