---
description: Machine installation materializes repository-owned regular-file template
  layers into the TeleClaude home, every declared person and company home, and every
  enabled help desk inside them before the retained history is activated.
---

# Home Template Materialization — Spec

## Required reads

@docs/local/spec/domain/reconciliation.md

## What it is

The home templates are the source for repository-owned regular files that
machine installation places into the TeleClaude home and into the homes it
holds: every declared person home, every declared company home, and every
enabled help desk inside the TeleClaude home or a company home. Each target
receives one or more template layers at matching relative paths. Materialization
writes each template's rendered content rather than linking it, so an installed
home remains valid when the canonical checkout moves and every materialized file
remains eligible for the home's regular-file-only retained history.

Materialization runs on every machine installation, upgrades included, so every
home converges to the current templates. What a target keeps across
installations is decided by the template's name (the create-once marker in
`projects/teleclaude/spec/feature/reconciliation/template-installation`): an
<!-- planned-change:home-scoped-commits -->
`AGENTS.master.md` is the rendering of its template and is refreshed whenever it
differs, while a local baseline manifest is created once and then belongs to the
home that curates it (`general/policy/agent-artifact-governance`).
<!-- change:home-scoped-commits -->
`AGENTS.master.md` is the rendering of its template and is refreshed whenever it
differs, while a local baseline manifest is created once and then belongs to the
home that curates it (`general/policy/agent-artifact-governance`). A target
carrying a change no one has recorded is someone's work in progress:
installation leaves it untouched and reports it, and converges it on the first
installation after that change is recorded or discarded.
<!-- /planned-change:home-scoped-commits -->

Materialization precedes home-repository activation. The retained-set
declaration in the home layer is therefore both the declaration consumed by
membership decisions and the file recorded by activation; no parallel
declaration exists in application code. Projection-only template material may
be installed beside it without entering the retained set. Every retained target
materialization writes, new or refreshed, enters the activation's record, so a
refreshed retained file never leaves the home's working tree dirty.

A project's help desk lives in that project's repository, and machine
installation never writes into a project's working tree; it converges when the
project's initialization enables its help desk
(`projects/teleclaude/spec/feature/config/kind-addressed-configuration`).

## Canonical fields

- **Template trees.** Directories under `templates/` in the canonical
  TeleClaude checkout. A tree contributes only the files the checkout tracks.
- **Targets and their layers.**

| Target                                             | Present when                                     | Layers                                     |
| -------------------------------------------------- | ------------------------------------------------ | ------------------------------------------ |
| The TeleClaude home                                | always                                           | `templates/home`                           |
| A person home, `people/<slug>/`                    | the folder holds its person declaration          | `templates/docs`, `templates/home-person`  |
| A company home, `companies/<slug>/`                | the folder holds its company declaration         | `templates/docs`, `templates/home-company` |
| The platform help desk, `help-desk/`               | the global declaration enables its help desk     | `templates/help-desk-platform`             |
| A company help desk, `companies/<slug>/help-desk/` | that company's declaration enables its help desk | `templates/help-desk-company`              |

- **No documentation layer for the TeleClaude home.** The home's `docs/` is the
  published documentation generation
  (`projects/teleclaude/spec/teleclaude-home-layout`); no template is ever
  materialized into it.
- **Declared, not participating.** A person or company home is a target when
  its declaration exists, whether or not it participates in documentation
  publication.
- **Target mapping.** Each source path keeps its path relative to its layer,
  placed under the layer's directory in the target: `templates/docs` under the
  target's `docs/`, every other layer at the target's root, with every
  `dot_<name>` segment mapped to `.<name>` and a `create_<name>` file segment
  mapped to `<name>`.
- **Layer union.** A target receives the union of its layers' files. Two layers
  of one target that produce the same relative path fail installation before any
  target is written.
- **File kind.** Sources and targets are regular files. Symbolic links are never
  created by this materialization path.
<!-- planned-change:home-scoped-commits -->
- **Content gate.** Each template is rendered per the template-installation
  contract before comparison. An absent target is written. A target whose
  template is not create-once and whose bytes differ from the rendered content
  is rewritten; an identical target is left untouched. A create-once target
  that exists is kept whatever its content. An unresolved placeholder fails
  installation before any target is written.
<!-- change:home-scoped-commits -->
- **Content gate.** Each template is rendered per the template-installation
  contract before comparison. An absent target is written. A target whose
  template is not create-once and whose bytes differ from the rendered content
  is rewritten; an identical target is left untouched. A create-once target
  that exists is kept whatever its content. An unresolved placeholder fails
  installation before any target is written.
- **Unrecorded changes are held.** A retained target that differs from its
  last record — modified, staged, or present but never recorded, including
  before the history exists — is held: left byte for byte as it is, never
  recorded by activation, and reported by path. The held set is read before the
  first write, under the lock the sealed commit holds, and that lock is kept
  until activation has recorded. A target the retained set excludes is never
  held.
<!-- /planned-change:home-scoped-commits -->
- **Conflict posture.** Every target of every home is validated before the first
  write. A source or target whose filesystem type is not a regular file fails
  installation, naming the path, before any target is replaced or removed.
- **Activation order.** Every layer of every target is materialized before the
  activation scan and activation commit begin.
- **Retained-set source.** `templates/home/dot_gitignore` is the one declaration
  consumed by membership evaluation and copied to the home's `.gitignore` for
  activation.

### Use cases

#### UC-HTM1: Installation materializes home templates as regular files

```gherkin
Given the canonical checkout contains repository-owned home templates
And dot-prefixed target paths use the dot_ source marker
And a target under the TeleClaude home is absent, identical, or byte-different
When an agent runs machine installation
Then every template is present at its mapped home-relative path as a regular file
And an identical target is left untouched
And a missing target, or one differing from the template's rendered content, receives that rendered content
And no materialized target is a symbolic link
```

#### UC-HTM2: A filesystem-type conflict fails without deleting the target

```gherkin
Given a home template source is a regular file
And its matching target exists with a different filesystem type
When an agent runs machine installation
Then installation identifies the conflicting target and exits non-zero
And the conflicting target is not removed or replaced
And home-repository activation does not begin
```

#### UC-HTM3: Activation records the materialized retained-set declaration

```gherkin
Given the home template tree carries its dot_gitignore declaration and dot_vscode projection-only settings
When an agent runs machine installation
Then the templates are materialized before the activation scan begins
And membership evaluation consumes the same retained-set declaration that activation records
And the projection-only settings remain outside the retained set
```

#### UC-HTM4: Installation converges every declared person and company home

<!-- planned-change:home-scoped-commits -->
```gherkin
Given a declared person home and a declared company home
And one holds an AGENTS.master.md that differs from its template and local baselines its owner has edited
And the other holds neither a master nor local baselines
When an agent runs machine installation
Then each home's AGENTS.master.md equals the rendering of its kind's template
And the edited local baselines keep their content byte for byte
And the missing local baselines are created from the documentation layer
And no documentation taxonomy directory is created in either home
```
<!-- change:home-scoped-commits -->
```gherkin
Given a declared person home and a declared company home
And one holds a recorded AGENTS.master.md that differs from its template, with no unrecorded change, and local baselines its owner has edited
And the other holds neither a master nor local baselines
When an agent runs machine installation
Then each home's AGENTS.master.md equals the rendering of its kind's template
And the edited local baselines keep their content byte for byte
And the missing local baselines are created from the documentation layer
And no documentation taxonomy directory is created in either home
```
<!-- /planned-change:home-scoped-commits -->

#### UC-HTM5: The TeleClaude home receives no documentation layer

```gherkin
Given the TeleClaude home holds the published documentation generation under docs/
When an agent runs machine installation
Then no file under the home's docs/ is written or replaced by materialization
And the home's own master comes from the home layer alone
```

#### UC-HTM6: An enabled help desk converges with its home

```gherkin
Given the global declaration enables the platform help desk
And one company declaration enables its help desk while another does not
When an agent runs machine installation
Then the platform help desk and the enabling company's help desk each hold the rendering of their kind's template
And nothing is written for the company whose help desk is not enabled
```

#### UC-HTM7: A refreshed retained file enters the activation record

<!-- planned-change:home-scoped-commits -->
```gherkin
Given a person home's retained AGENTS.master.md differs from its template
When an agent runs machine installation
Then the refreshed master is recorded by the activation commit
And the home's working tree holds no change to a retained path afterward
```
<!-- change:home-scoped-commits -->
```gherkin
Given a person home's retained AGENTS.master.md differs from its template and carries no unrecorded change
When an agent runs machine installation
Then the refreshed master is recorded by the activation commit
And the home's working tree holds no change to a retained path afterward
```
<!-- /planned-change:home-scoped-commits -->

#### UC-HTM8: Two layers producing one path fail before any write

```gherkin
Given two layers of one target each carry a template that maps to the same relative path
When an agent runs machine installation
Then installation fails naming that path and both layers
And no target of any home is written
And home-repository activation does not begin
```
<!-- planned:home-scoped-commits -->

#### UC-HTM9: A target carrying an unrecorded change is held

```gherkin
Given the TeleClaude home's history is active
And a person home's AGENTS.master.md carries an edit no one has recorded
And a company home's AGENTS.master.md is present but has never been recorded
When an agent runs machine installation twice
Then both files keep their content byte for byte
And neither file is recorded by activation
And each installation reports both paths as held because of their unrecorded change
```

#### UC-HTM10: A held target converges once its change is recorded

```gherkin
Given a person home's AGENTS.master.md was held because of an unrecorded edit
And its author has since recorded that edit
When an agent runs machine installation
Then the master equals the rendering of its template
And the refresh is recorded by the activation commit
```
<!-- /planned:home-scoped-commits -->

## Known caveats

- Template removal is not a pruning contract. Materialization creates or
  refreshes declared targets; it does not delete a home file merely because a
  later checkout no longer carries a matching template, and a help desk whose
  home stops enabling it keeps its folder.
- One malformed home fails the whole installation. The failure names the path,
  and no home is half-converged.
