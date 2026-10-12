---
description: 'Policy for referencing documentation snippets in AI agent prompts.'
visibility: 'public'
---

# Referencing Doc Snippets — Policy

## Rules

- Use inline `@` references only for **static Required reads declarations** in published agent artifacts and documentation snippets. They are expanded when those artifacts are assembled.
- Runtime-generated briefs, formatter messages, and peer messages must never use inline `@` references. Name the canonical snippet ID and, when needed, the `telec docs get <id>` invocation instead. Expanding a reference into an already-running session duplicates context and bypasses that session's own required-read discipline.
- Global doc references must use the absolute-home form
  `@<HOME>/.teleclaude/docs/...` (e.g. `@<HOME>/.teleclaude/docs/...`).
  This matches the enforced validator behavior at
  `teleclaude/resource_validation/_snippet.py:124` which expands
  `Path.home()` at validation time; the unexpanded `@~/...` literal
  is NOT accepted by the validator.
- A published domain's generated baseline bundle is a valid global Required Read at
  `@<HOME>/.teleclaude/docs/<domain>/bundle.md`. This exact generated-artifact
  shape is the sole exception to the taxonomy-segment requirement. Validation accepts it only
  for a published domain, and deploy mode generates it before agent-artifact transpilation.
- A generated global documentation artifact resolves to the published generation, never to a
  publisher source tree. The merged index and every published domain's baseline bundle are the
  artifacts this covers; every authored global snippet resolves to the project that owns it.
- Local doc references use `@docs/local/...`, relative to the root of the home
  that holds both the referencing and the referenced snippet.
- References to a person's or company's published snippets use the
  absolute-home form of the tier's published address:
  `@<HOME>/.teleclaude/docs/companies/<slug>/...` or
  `@<HOME>/.teleclaude/docs/people/<slug>/...`. Such a reference resolves to
  its source in that tier's `docs/global`. A tier snippet's Required reads name
  only its own tier and global documentation.
- A published snippet never references local material, neither as a Required
  read nor as a citation. It states the general contract. How one home realizes
  that contract lives in the home's own local snippets, which agents working
  there load themselves.
- A local snippet references its own home's local snippets or published ones,
  never another home's local snippets.
- A placeholder pattern that names the reader's own home — `local/projects/<slug>/…`
  where `<slug>` is the reader's project — is a pattern, not a reference, and may
  appear in any snippet.
- Third-party sources must appear under **See also** only (soft references).
  They must not appear in Required reads.

### Inline citations

- A rule another snippet owns is cited in prose, never restated: a one-clause
  gist followed by the owner's backticked id — _orient the human before a
  consequential move (`general/policy/leadership`)_. The gist carries the rule's
  force where the reader acts; the id routes the reader to the single place that
  states it in full, with its reason. A Gherkin scenario is a rule for this
  purpose: a predicate another spec owns is not re-authored as a use case under
  a different actor or surface; the citing spec carries its one-sentence
  contribution and the owner's id.
- A bare backticked id is a pointer, not a citation. Use it where the reader
  needs to know where something lives, not what it requires.
- Cite by id only — never by file path, never by section anchor. A rule that can
  only be located with an anchor lives in a snippet too large to own it.
- A citation never paraphrases the owner beyond its gist. When the citing text
  needs more of the rule than one clause carries, the reader needs the owner:
  make it a Required read, or narrow the citing text so one clause suffices.

## Rationale

- Inline `@` references are the single enforced mechanism for mandatory reading declared by a static artifact. Runtime instructions name the required snippet without expanding it so the receiving session controls the read once.
- A stable global root (`~/.teleclaude/docs`, written as the absolute-
  home form `<HOME>/.teleclaude/docs/...`) prevents ambiguity across
  repos. The validator expands `Path.home()` per-machine, so refs
  remain machine-local but consistent within one operator's environment.
- Repo‑relative `@docs/...` keeps project docs portable and consistent.
- A published snippet is read in every home, and a local snippet only in its
  own. A citation into local material is a dead end for every other reader, and
  it ties the general contract to one home's implementation. The dependency runs
  from the specific toward the general, never the reverse.
- A tier's published address carries its owner slug, so one form stays
  unambiguous when several companies are read together. A Required read into
  another person's or company's tier would demand reach the reader may not hold,
  so the dependency could not be honoured for every reader of the snippet.
- Soft references prevent third-party docs from being auto-included in agent context.
- A rule stated in two snippets is two rules to a reader: each wording is read
  as possibly distinct, and the copies drift until they contradict. The gist
  keeps the emphasis a repetition was reaching for; the id keeps one owner.
- An authored global snippet resolves to its publisher source because that source is readable
  before a host has published anything. A generated artifact has no such source, so the same
  mapping substitutes a file nothing regenerates for the one the reference names. The substitute
  keeps resolving, so the reference looks healthy while its content stops tracking the sources it
  was generated from, and every artifact compiled from it inherits the stale copy with no check
  failing.

## Scope

- Applies to all AI agents, all repositories, and all documentation references in static artifacts or runtime messages.
- Static-declaration rules apply to `AGENTS.md`, baseline indexes, commands, agents, and any doc snippet that requires prerequisites.

## Enforcement

- Static Required reads must appear in a `Required reads` section immediately after the H1 title (or after the activation line in commands/agents).
- Static Required reads must use inline `@` references only.
- Runtime brief, formatter, and peer-message output containing an inline `@` documentation reference is a defect.
- Soft references must appear in a `See also` section at the bottom and must not use `@`.
- Reviewers treat a restated rule whose owner is another snippet as a finding and
  replace it with a citation.
- Reviewers apply the reference rules to every changed reference, inline
  citations included. Whether a backticked id in prose is a citation, an example, or a
  placeholder is a reading judgment, so no scanner checks inline citations
  (`general/principle/intelligence-boundaries`).

## Exceptions

- None.

## See Also

- ~/.teleclaude/docs/general/procedure/agent-artifact-authoring.md
