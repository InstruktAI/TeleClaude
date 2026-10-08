---
description: Machine installation materializes the TeleClaude home's repository layer and every declared person and company home's documentation baselines before the retained history is activated, while help desks and template-rendered home masters are deployment output that convergence renders and no history ever records.
---

# Home Template Materialization — Spec

## Required reads

@docs/local/spec/domain/reconciliation.md

## What it is

The home templates are the source for repository-owned regular files placed
into the TeleClaude home and into the homes it holds. They fall into two kinds
of material with two renderers.

- **The home's repository layer.** Machine installation materializes the
  TeleClaude home's retained-set declaration and its projection-only editor
  settings, and creates the documentation baselines every declared person and
  company home is missing. Materialization runs on every machine installation,
  upgrades included, and precedes home-repository activation, which records
  what it writes. A baseline is created once and then belongs to the home that
  curates it (`general/policy/agent-artifact-governance`); the template's name
  decides that through the create-once marker in
  `local/projects/teleclaude/spec/feature/reconciliation/template-installation`.
- **Deployment output.** The TeleClaude home's root master, each declared person
  and company home's master, the platform help desk and each company help desk
  are renderings of their kind's template. They are git-ignored, never part of
  any repository, and nothing in them changes in place: a target that differs
  from its rendered template is rewritten, and no history ever records it.
  Machine installation renders none of them. The configuration-aware
  convergence renders them at the commit boundary and through `telec sync`
  (`local/projects/teleclaude/spec/feature/reconciliation/project-plumbing-convergence`).

Materialization writes each template's rendered content rather than linking it,
so an installed home remains valid when the canonical checkout moves and every
retained file remains eligible for the home's regular-file-only retained
history. A retained target carrying a change no one has recorded is someone's
work in progress: installation leaves it untouched and reports it, and
converges it on the first installation after that change is recorded or
discarded.

The retained-set declaration in the home's repository layer is both the
declaration consumed by membership decisions and the file recorded by
activation; no parallel declaration exists in application code. It admits no
`AGENTS.master.md` and nothing inside a help desk. Every retained target
materialization writes, new or refreshed, enters the activation's record, so a
refreshed retained file never leaves the home's working tree dirty.

A project's help desk is deployment output of the same kind, rendered into the
project's working tree by that project's convergence while its declaration
enables it; machine installation never writes into a project's working tree.

## Canonical fields

- **Template trees.** Directories under `templates/` in the canonical
  TeleClaude checkout. A tree contributes only the files the checkout tracks.
- **Targets, material and renderer.**

| Target                                             | Present when                                     | Material                                                    | Rendered by  |
| -------------------------------------------------- | ------------------------------------------------ | ----------------------------------------------------------- | ------------ |
| The TeleClaude home                                | always                                           | `templates/home`: retained-set declaration, editor settings | installation |
| The TeleClaude home's root master                  | always                                           | its kind's master template                                  | convergence  |
| A person home, `people/<slug>/`                    | the folder holds its person declaration          | `templates/docs` baselines                                  | installation |
| A person home's master                             | the folder holds its person declaration          | `templates/home-person`                                     | convergence  |
| A company home, `companies/<slug>/`                | the folder holds its company declaration         | `templates/docs` baselines                                  | installation |
| A company home's master                            | the folder holds its company declaration         | `templates/home-company`                                    | convergence  |
| The platform help desk, `help-desk/`               | the global declaration enables its help desk     | `templates/help-desk-platform`                              | convergence  |
| A company help desk, `companies/<slug>/help-desk/` | that company's declaration enables its help desk | `templates/help-desk-company`                               | convergence  |
| A project help desk, `<project>/help-desk/`        | that project's declaration enables its help desk | `templates/help-desk-project`                               | convergence  |

- **No documentation layer for the TeleClaude home.** The home's `docs/` is the
  published documentation generation
  (`local/projects/teleclaude/spec/teleclaude-home-layout`); no template is ever
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
  of one target that produce the same relative path fail before any target is
  written.
- **File kind.** Sources and targets are regular files. Symbolic links are never
  created by this materialization path.
- **Content gate.** Each template is rendered per the template-installation
  contract before comparison. An absent target is written. A target whose
  template is not create-once and whose bytes differ from the rendered content
  is rewritten; an identical target is left untouched. A create-once target
  that exists is kept whatever its content. An unresolved placeholder fails
  before any target is written.
- **Deployment output is ignored, never held.** A desk folder ignores itself
  through its converged ignore file, and the home's retained set excludes every
  master, so deployment output is never recorded and never held. A deployment
  output path that git tracks is not written; convergence reports it with the
  untrack that resolves it.
- **Unrecorded changes are held.** A retained target that differs from its
  last record — modified, staged, or present but never recorded, including
  before the history exists — is held: left byte for byte as it is, never
  recorded by activation, and reported by path. The held set is read before the
  first write, under the lock the sealed commit holds, and that lock is kept
  until activation has recorded. A target the retained set excludes is never
  held.
- **Conflict posture.** Every installation target of every home is validated
  before the first write. A source or target whose filesystem type is not a
  regular file fails installation, naming the path, before any target is
  replaced or removed.
- **Activation order.** Every installation layer of every target is
  materialized before the activation scan and activation commit begin.
- **Retained-set source.** `templates/home/dot_gitignore` is the one declaration
  consumed by membership evaluation and copied to the home's `.gitignore` for
  activation.

### Use cases

#### UC-HTM1: Installation materializes home templates as regular files

```gherkin
Given the canonical checkout contains repository-owned home repository-layer templates
And dot-prefixed target paths use the dot_ source marker
And a target under the TeleClaude home is absent, identical, or byte-different
When an agent runs machine installation
Then every repository-layer template is present at its mapped home-relative path as a regular file
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

#### UC-HTM4: Installation creates missing baselines and renders no master

```gherkin
Given a declared person home and a declared company home
And one holds local baselines its owner has edited
And the other holds no local baselines
When an agent runs machine installation
Then the edited local baselines keep their content byte for byte
And the missing local baselines are created from the documentation layer
And no AGENTS.master.md in either home is written by installation
And no documentation taxonomy directory is created in either home
```

#### UC-HTM5: The TeleClaude home receives no documentation layer

```gherkin
Given the TeleClaude home holds the published documentation generation under docs/
When an agent runs machine installation
Then no file under the home's docs/ is written or replaced by materialization
```

#### UC-HTM6: Installation renders no help desk

```gherkin
Given the global declaration enables the platform help desk
And a company declaration enables its help desk
When an agent runs machine installation
Then nothing is written into the platform help desk or the company help desk
And neither desk folder enters the activation's record
```

#### UC-HTM7: A refreshed retained file enters the activation record

```gherkin
Given the TeleClaude home's retained .gitignore differs from its template and carries no unrecorded change
When an agent runs machine installation
Then the refreshed .gitignore is recorded by the activation commit
And the home's working tree holds no change to a retained path afterward
```

#### UC-HTM8: Two layers producing one path fail before any write

```gherkin
Given two layers of one target each carry a template that maps to the same relative path
When an agent runs machine installation
Then installation fails naming that path and both layers
And no target of any home is written
And home-repository activation does not begin
```

#### UC-HTM9: A target carrying an unrecorded change is held

```gherkin
Given the TeleClaude home's history is active
And the home's retained .gitignore carries an edit no one has recorded
When an agent runs machine installation twice
Then the file keeps its content byte for byte
And it is not recorded by activation
And each installation reports its path as held because of its unrecorded change
```

#### UC-HTM10: A held target converges once its change is recorded

```gherkin
Given the TeleClaude home's retained .gitignore was held because of an unrecorded edit
And its author has since recorded that edit
When an agent runs machine installation
Then the .gitignore equals the rendering of its template
And the refresh is recorded by the activation commit
```

## Known caveats

- Template removal is not a pruning contract. Materialization and convergence
  create or refresh declared targets; neither deletes a home file merely
  because a later checkout no longer carries a matching template.
- A help desk whose home stops enabling it keeps its folder in place, and the
  desk is no longer hosted.
- One malformed home fails the whole installation. The failure names the path,
  and no home is half-converged.
