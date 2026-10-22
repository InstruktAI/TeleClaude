---
description: Machine installation materializes the TeleClaude home's repository layer and every declared person and company home's documentation baselines before the retained history is activated, while convergence seeds each missing home master and help desk once and its home's history then records it as the home's own source.
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

- **Seeded masters.** Each declared person and company home's master and each
  enabled company help desk are seeded from their kind's template. Seeding
  writes a master only while it is absent; an existing master is never
  rewritten, whatever its content, and the home's history records it like any
  other source the home owns. Machine installation seeds none of them. The
  configuration-aware convergence seeds them at the commit boundary and through
  `telec sync`
  (`local/projects/teleclaude/spec/feature/reconciliation/project-plumbing-convergence`).
  The TeleClaude home's root master has no template: it is authored in the
  home and recorded by its history.

Materialization writes each template's rendered content rather than linking it,
so an installed home remains valid when the canonical checkout moves and every
retained file remains eligible for the home's regular-file-only retained
history. A retained target carrying a change no one has recorded is someone's
work in progress: installation leaves it untouched and reports it, and
converges it on the first installation after that change is recorded or
discarded.

The retained-set declaration in the home's repository layer is both the
declaration consumed by membership decisions and the file recorded by
activation; no parallel declaration exists in application code. It admits the
fixed home master set (`local/projects/teleclaude/spec/teleclaude-home-layout`)
and nothing else inside a help desk. Every retained target
materialization writes, new or refreshed, enters the activation's record, so a
refreshed retained file never leaves the home's working tree dirty.

A project's help desk is seeded the same way, into the project's repository,
by that project's convergence while its declaration enables it, and the project
records it; machine installation never writes into a project's working tree.
Company help desks are likewise outside machine installation: it writes no desk
files and does not add a desk folder to the activation record. Baseline
materialization creates the missing baseline files, not an additional
documentation taxonomy scaffold.

## Canonical fields

- **Template trees.** Directories under `templates/` in the canonical
  TeleClaude checkout. A tree contributes only the files the checkout tracks.
- **Targets, material and renderer.**

| Target                                             | Present when                                     | Material                                                    | Rendered by  |
| -------------------------------------------------- | ------------------------------------------------ | ----------------------------------------------------------- | ------------ |
| The TeleClaude home                                | always                                           | `templates/home`: retained-set declaration, editor settings | installation |
| A person home, `people/<slug>/`                    | the folder holds its person declaration          | `templates/docs` baselines                                  | installation |
| A person home's master                             | the folder holds its person declaration          | `templates/home-person`, create-once                        | convergence  |
| A company home, `companies/<slug>/`                | the folder holds its company declaration         | `templates/docs` baselines                                  | installation |
| A company home's master                            | the folder holds its company declaration         | `templates/home-company`, create-once                       | convergence  |
| A company help desk, `companies/<slug>/help-desk/` | that company's declaration enables its help desk | `templates/help-desk-company`, master create-once           | convergence  |
| A project help desk, `<project>/help-desk/`        | that project's declaration enables its help desk | `templates/help-desk-project`, master create-once           | convergence  |

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
  written, naming that path and both contributing layers.
- **File kind.** Sources and targets are regular files. Symbolic links are never
  created by this materialization path.
- **Content gate.** Each template is rendered per the template-installation
  contract before comparison. An absent target is written. A target whose
  template is not create-once and whose bytes differ from the rendered content
  is rewritten; an identical target is left untouched. A create-once target
  that exists is kept whatever its content. An unresolved placeholder fails
  before any target is written.
- **Seeded masters are never rewritten.** A master template is create-once, so
  convergence writes a master only while it is absent and leaves an existing
  one as it is. A desk's ignore file converges to its kind's template and
  ignores everything in the desk except what its home records.
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

#### UC-HTM2: A filesystem-type conflict fails without deleting the target

#### UC-HTM3: Activation records the materialized retained-set declaration

#### UC-HTM4: An operator installs without losing edited home baselines

```gherkin
Given a declared person home has owner-edited documentation baselines
And a declared company home is missing its documentation baselines
When the operator runs machine installation
Then the edited baselines remain byte for byte unchanged
And the missing baselines are created from the documentation layer
And neither home's master file is seeded by installation
```

#### UC-HTM5: The TeleClaude home receives no documentation layer

#### UC-HTM6: Installation renders no help desk

#### UC-HTM7: A refreshed retained file enters the activation record

#### UC-HTM8: Two layers producing one path fail before any write

#### UC-HTM9: An operator preserves unrecorded home edits during installation

```gherkin
Given the home's retained .gitignore contains an unrecorded local edit
When the operator runs machine installation
Then the file remains byte for byte unchanged
And activation does not record the file
And installation reports that path as held because of its unrecorded change
```

#### UC-HTM10: A held target converges once its change is recorded

## Known caveats

- Template removal is not a pruning contract. Materialization and convergence
  create or refresh declared targets; neither deletes a home file merely
  because a later checkout no longer carries a matching template.
- A help desk whose home stops enabling it keeps its folder in place, and the
  desk is no longer hosted.
- Seeding records nothing. A master convergence seeds stays uncommitted until
  its home records it, and publication compiles it only from that commit.
- A template change reaches only masters seeded after it; an existing master
  keeps its content until its home edits it.
- One malformed home fails the whole installation. The failure names the path,
  and no home is half-converged.
