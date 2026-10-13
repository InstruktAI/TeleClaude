---
description: Schema, path, ref, and section-shape validation enforced on every taxonomy
  source snippet during source validation.
visibility: public
---

# Snippet Frontmatter Validation — Spec

## Required reads

- @docs/local/spec/domain/context.md

## What it is

Snippet frontmatter validation is the context gate that runs on every taxonomy
source file during source validation and the pre-commit markdown gate. It enforces
the schema of Context snippets so the Index, selection policy, and CRUD
surface never observe broken frontmatter, broken Required reads, leaked inline
refs, wrong H1 type suffixes, or wrong taxonomy sections. Validation enforces
presence of the authored `description`, correct Required-reads placement,
inline-ref scoping, H1 type-suffix consistency, and per-type section shape —
where the type is derived from the path, not from frontmatter.
`id`/`type`/`scope`/`domain` are path-derived and never authored, so there is no
id-to-path check. A person or company tier source that authors any of them
receives a finding naming each authored field.

A Required read or inline reference whose address is well-formed but names a
domain that no project registered on this computer publishes is reported with
config's refusal for that domain
(`local/projects/teleclaude/spec/feature/config/referent-resolution`), never as
a malformed reference; the snippet carrying it is otherwise validated in full.

Frontmatter shape is always validated: `delivered_by`, when present, must be a
non-empty list of slug strings; absence means the snippet is current. No
`status` field is validated or required. When publication runs with the
todos DB reachable, relationship state is additionally validated against the
**local** todos store: every `delivered_by` slug and every in-body planned /
planned-change marker slug is checked. A slug resolving to a retained todo —
active, icebox, or soft-removed — is tolerated. A slug that names **no todo in
the local store is expected and not reported**: todos are machine-local, so a
snippet carried in git routinely references an in-flight todo that lives on
another computer, or one already hard-purged with its markers folded by
maintenance. A slug resolving to a **delivered** todo is reported only when the
validated checkout contains that todo's delivery commit. A delivered todo whose
delivery commit is unrecorded is not reported. Scoped per-file runs and runs
without a reachable todos DB validate shape only.

## Canonical fields

### Use cases

```
Scenario: Missing required frontmatter field
  Given a snippet file without a "description" key in frontmatter
  When source validation runs over the file
  Then a missing-frontmatter-field finding is reported for "description"
  And validation exits with a non-zero status
```

```
Scenario: delivered_by is an empty list
  Given a snippet with an empty delivered_by list
  When validation runs
  Then a "snippet_delivered_by_invalid_shape" finding is reported
```

```
Scenario: delivered_by relationship state is validated on a full run
  Given a snippet with delivered_by ["already-delivered-slug"]
  And the todos DB is reachable (full run)
  And the checkout contains that todo's delivery commit
  When snippet validation runs
  Then a "snippet_delivered_by_invalid_slug" finding is reported
Scenario: delivered_by naming a delivered todo whose delivery commit the checkout lacks is tolerated
  Given a snippet with delivered_by ["already-delivered-slug"]
  And the todos DB is reachable (full run)
  And the checkout does not contain that todo's delivery commit
  When snippet validation runs
  Then no relationship finding is reported
Scenario: delivered_by naming a delivered todo with no recorded delivery commit is tolerated
  Given a snippet with delivered_by ["already-delivered-slug"]
  And the todos DB records no delivery commit for that todo
  When snippet validation runs
  Then no relationship finding is reported
Scenario: delivered_by naming a soft-removed todo is tolerated
  Given a snippet with delivered_by ["removed-slug"]
  And the todos DB reports "removed-slug" as removed (full run)
  When snippet validation runs
  Then no relationship finding is reported
Scenario: delivered_by naming a slug absent from the local store is tolerated
  Given a snippet with delivered_by ["unknown-slug"]
  And the todos DB has no todo "unknown-slug" (full run)
  When snippet validation runs
  Then no relationship finding is reported
Scenario: delivered_by relationship state is not checked on a scoped run
  Given a snippet with delivered_by ["already-delivered-slug"]
  And validation runs per-file without the todos DB
  When snippet validation runs
  Then the shape is accepted and no relationship finding is reported
```

#### UC-SFV1: Planned-change marker shape is validated mechanically

```
Given a snippet contains a planned-change block with matching open, change, and close markers
When snippet validation runs
Then no planned-change marker finding is reported
Given a snippet contains a planned-change block with a missing close marker, mismatched slug, or missing change separator
When snippet validation runs
Then a planned-change marker finding is reported
```

#### UC-SFV1b: In-body marker slug liveness is validated on full runs

```
Given a snippet contains an in-body planned or planned-change marker whose slug resolves to a delivered todo
And the todos DB is reachable (full run)
And the checkout contains that todo's delivery commit
When snippet validation runs
Then a "snippet_planned_marker_invalid_slug" finding is reported for that slug
Given the marker slug resolves to a delivered todo whose delivery commit the checkout does not contain, or whose delivery commit is unrecorded
When snippet validation runs
Then no marker-liveness finding is reported
Given the marker slug resolves to a retained todo (active, icebox, or soft-removed), or names no todo in the local store
When snippet validation runs
Then no marker-liveness finding is reported
Given the marker appears only inside an inline code span or a fenced code block (a syntax example)
When snippet validation runs
Then no marker-liveness finding is reported
Given validation runs per-file or without a reachable todos DB
When snippet validation runs
Then marker-liveness is not checked
```

#### UC-SFV1c: In-body markers must be whole-line, non-nested, and balanced

```
Given a snippet contains a planned, planned-change, or change marker with non-whitespace text before its opening "<!--" or after its closing "-->" on the same line
When snippet validation runs
Then a "snippet_marker_not_line_level" finding is reported for that marker
Given a snippet contains an in-body block whose markers each occupy their own line, is balanced, and no other slug's marker opens between its open and close
When snippet validation runs
Then no line-level, balance, or nesting finding is reported
Given a snippet contains a planned ADD opening marker with no matching close, a close with no matching open, or a close whose slug differs from the open
When snippet validation runs
Then a "snippet_marker_unbalanced" finding is reported for that marker
Given a snippet contains an in-body block (planned or planned-change) that opens while another in-body block is still open
When snippet validation runs
Then a "snippet_marker_nested" finding is reported for the inner marker
Given a snippet contains a planned ADD block whose opening marker is never closed, or a planned close marker with no matching open, or a planned close whose slug differs from its open
When snippet validation runs
Then a "snippet_marker_unbalanced" finding is reported for the unbalanced marker
Given a snippet contains a planned ADD marker whose slug is not kebab-case
When snippet validation runs
Then a "snippet_marker_invalid_slug" finding is reported for that marker
Given the marker appears only inside an inline code span or a fenced code block (a syntax example)
When snippet validation runs
Then no line-level, balance, or nesting finding is reported
```

#### UC-SFV2: H1 type suffix is validated from the path-derived type

```
Given a taxonomy snippet whose path-derived type is "policy"
And its H1 does not end with "— Policy"
When snippet validation runs
Then a snippet_title_suffix_invalid finding is reported for that file
Given the same taxonomy snippet's H1 ends with "— Policy"
When snippet validation runs
Then no title-suffix finding is reported
Given a pending companion for a policy snippet
When snippet validation runs on the companion
Then the required H1 suffix is still derived from the parent policy path
```

```
Scenario: Required reads is not the first H2
  Given a snippet whose first H2 after H1 is "## What it is"
  And a "## Required reads" H2 appears later
  When validation runs
  Then a "Required reads not first H2" finding is reported
```

```
Scenario: Inline @ ref leaks outside Required reads
  Given a snippet whose "## Canonical fields" body contains "@docs/other.md"
  And the inline @ ref is not inside an inline code span
  When validation runs
  Then a "Required reads outside section" finding is reported
```

```
Scenario: Per-type required sections missing
  Given a snippet whose path-derived type is "spec" without a "## Canonical fields" H2
  When section-shape validation runs
  Then a missing-section error is reported listing the required H2
```

#### UC-SFV3: A procedure declares one activation mode, never two

```
Given a procedure snippet declares both the events that activate it and a self-selection activation trigger
When snippet validation runs
Then an activation-mode conflict finding is reported for that file
And the sync exits with a non-zero status
Given a procedure snippet declares only the events that activate it
When snippet validation runs
Then no activation-mode finding is reported
Given a procedure snippet declares only a self-selection activation trigger
When snippet validation runs
Then no activation-mode finding is reported
Given a procedure snippet declares neither activation mode
When snippet validation runs
Then no activation-mode finding is reported
```

#### UC-SFV4: Only a procedure published where subscriptions are routed may declare them

```
Given a procedure snippet published in the global tier, in a company's tier, or in a person's tier declares the events that activate it
When snippet validation runs
Then no subscription-tier finding is reported
Given a procedure snippet published in any other tier declares the events that activate it
When snippet validation runs
Then a subscription-tier finding is reported for that file, naming its tier
And the sync exits with a non-zero status
```

#### UC-SFV5: An empty companion is accepted as a retirement

```
Given an agent commits a zero-byte sibling companion naming a slug beside a live snippet
When snippet validation runs on that commit
Then the agent receives no frontmatter, title-suffix, or section finding for the companion
And the live snippet is still validated in full
```

#### UC-SFV6: A subscribed procedure declares the one home kind it answers

```gherkin
Scenario Outline: The answered home kind is validated against the subscription and the tier
  Given a procedure snippet published in <tier> <declaration>
  When snippet validation runs
  Then <outcome>

  Examples:
    | tier                | declaration                                                | outcome                                                                     |
    | the global tier     | declares its events and answers company events            | no home-kind finding is reported                                            |
    | the global tier     | declares its events and answers person events             | no home-kind finding is reported                                            |
    | the global tier     | declares its events and answers project events            | no home-kind finding is reported                                            |
    | the global tier     | declares its events and answers platform events           | no home-kind finding is reported                                            |
    | a company's tier    | declares its events and answers company events            | no home-kind finding is reported                                            |
    | a person's tier     | declares its events and answers person events             | no home-kind finding is reported                                            |
    | the global tier     | declares its events and no home kind                      | a home-kind finding is reported for that file and the sync exits non-zero   |
    | the global tier     | declares a home kind and no events                        | a home-kind finding is reported for that file and the sync exits non-zero   |
    | the global tier     | declares its events and a home kind outside the four      | a home-kind finding is reported for that file and the sync exits non-zero   |
    | a company's tier    | declares its events and answers project events            | a home-kind finding naming the tier is reported and the sync exits non-zero |
    | a person's tier     | declares its events and answers company events            | a home-kind finding naming the tier is reported and the sync exits non-zero |
```

#### UC-SFV7: A subscription is a type pattern

```gherkin
Scenario Outline: Each declared subscription is checked against the type-pattern forms
  Given a procedure snippet answering company events declares the subscription "<subscription>"
  When snippet validation runs
  Then <outcome>

  Examples:
    | subscription     | outcome                                                                                 |
    | erp.invoice.paid | no subscription finding is reported                                                     |
    | erp.invoice.*    | no subscription finding is reported                                                     |
    | *                | no subscription finding is reported                                                     |
    | erp.inv*         | a subscription finding naming the pattern is reported and the sync exits non-zero       |
    | erp.*.paid       | a subscription finding naming the pattern is reported and the sync exits non-zero       |
    | *.paid           | a subscription finding naming the pattern is reported and the sync exits non-zero       |
```

#### UC-SFV8: A subscribed procedure may declare which agent answers each event

```gherkin
Scenario Outline: The declared agent identity is validated against the subscription
  Given a procedure snippet published in the global tier <declaration>
  When snippet validation runs
  Then <outcome>

  Examples:
    | declaration                                                  | outcome                                                                         |
    | declares its events and no agent identity                    | no agent-identity finding is reported                                           |
    | declares its events and the home agent identity              | no agent-identity finding is reported                                           |
    | declares its events and the subject agent identity           | no agent-identity finding is reported                                           |
    | declares its events and an agent identity outside the two    | an agent-identity finding is reported for that file and the sync exits non-zero |
    | declares an agent identity and no events                     | an agent-identity finding is reported for that file and the sync exits non-zero |
```

#### UC-SFV9: A subscribed procedure may declare that no person watches its agent

```gherkin
Scenario Outline: The declared attendance is validated against the subscription
  Given a procedure snippet published in the global tier <declaration>
  When snippet validation runs
  Then <outcome>

  Examples:
    | declaration                                             | outcome                                                                      |
    | declares its events and no attendance                   | no attendance finding is reported                                            |
    | declares its events and the attended attendance         | no attendance finding is reported                                            |
    | declares its events and the unattended attendance       | no attendance finding is reported                                            |
    | declares its events and an attendance outside the two   | an attendance finding is reported for that file and the sync exits non-zero |
    | declares an attendance and no events                    | an attendance finding is reported for that file and the sync exits non-zero |
```

#### UC-SFV10:

```gherkin
Scenario Outline: Event delivery declarations are validated structurally
  Given an agent authors a procedure with <declaration>
  When the agent validates its documentation
  Then it receives <result>

  Examples:
    | declaration                                                    | result                                      |
    | subscriptions and either supported delivery mode               | an accepted declaration                     |
    | subscriptions and either boolean interruptibility value        | an accepted declaration                     |
    | subscriptions and omitted delivery settings                    | an accepted declaration using the defaults  |
    | subscriptions and an unsupported delivery mode                 | a finding identifying the invalid setting   |
    | subscriptions and a non-boolean interruptibility value         | a finding identifying the invalid setting   |
    | delivery settings without subscriptions                        | a finding identifying the misplaced setting |
```

Publication resolves the declaration defaults and publishes the effective
delivery settings alongside the existing subscription facts. Field names,
values, defaults, and implied required reads are owned by
`general/spec/snippet-authoring-schema`; interpretation uses the same resolved
declaration for publication, retrieval, and activation routing
(`sdlc/principle/design-fundamentals`).

<!-- planned:procedure-role-capability-composition -->

#### UC-SFV11: A procedure's role declaration names a catalog role

```
Given a procedure declares `role`
When snippet validation runs
Then a value the agent role catalog does not name is a finding naming the snippet and the value
And the field on a non-procedure snippet is a finding
And a procedure declaring `subscriptions` without `role` is a finding
```

#### UC-SFV12: A procedure's parameters are well-formed

```
Given a procedure declares `parameters` beside `role`
When snippet validation runs
Then a duplicate parameter name, a `rest` entry that is not last, or a non-string default is a finding
And `parameters` on a snippet declaring no `role` is a finding
```

#### UC-SFV13: A procedure's dispatch defaults are well-formed

```
Given a procedure declares `dispatch` beside `role`
When snippet validation runs
Then an empty agent list, an unknown agent name, or an unknown thinking mode is a finding
And `dispatch` on a snippet declaring no `role` is a finding
```

<!-- /planned:procedure-role-capability-composition -->

### Cross-context references

- workflow and integration own lifecycle state transitions and delivery-time
  frontmatter reconciliation for `delivered_by`.

## Known caveats

- Validation findings are stdout text grouped by code and reason; consumers
  must parse text because there is no machine-readable output channel today.
- HTML comments inside `## Required reads` and `## See Also` are silently
  ignored.
- `activation_trigger` is allowed only on procedure snippets and is rejected
  on any other taxonomy type.
- `id`/`type`/`scope`/`domain` are derived from the Source's path, so no
  id-to-path mismatch check exists. Validation detects an authored
  classification field only on a person or company tier source; on a project or
  global source it goes unreported, and the index build derives the field from
  the path regardless.

## See Also

- docs/local/spec/feature/context/lifecycle-marker-reconciliation.md — the owner of the delivery fold, which performs the marker removal as part of the delivery commit.
