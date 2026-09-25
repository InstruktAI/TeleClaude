---
description: Machine installation materializes repository-owned regular-file templates
  into the TeleClaude home before the retained history is activated.
---

# Home Template Materialization — Spec

## Required reads

@docs/project/spec/domain/reconciliation.md

## What it is

<!-- planned-change:installable-template-trees -->
The home template tree is the source for repository-owned regular files that
machine installation places at matching relative paths under the TeleClaude
home. Materialization copies bytes rather than linking them, so the installed
home remains valid when the canonical checkout moves and every materialized
file remains eligible for the home's regular-file-only retained history.
<!-- change:installable-template-trees -->
The home template tree is the source for repository-owned regular files that
machine installation places at matching relative paths under the TeleClaude
home. Materialization writes each template's rendered content rather than
linking it, so the installed home remains valid when the canonical checkout
moves and every materialized file remains eligible for the home's
regular-file-only retained history.
<!-- /planned-change:installable-template-trees -->

Materialization precedes home-repository activation. The retained-set
declaration in the template tree is therefore both the declaration consumed by
membership decisions and the file recorded by activation; no parallel
declaration exists in application code. Projection-only template material may
be installed beside it without entering the retained set.

## Canonical fields

- **Source tree.** `templates/home/**` in the canonical TeleClaude checkout.
- **Target tree.** The TeleClaude home, preserving each source path relative to
  the source tree after mapping every `dot_<name>` path segment to `.<name>`.
- **Dotfile source names.** Dot-prefixed target files and directories use the
  `dot_<name>` marker in the source tree.
- **File kind.** Sources and targets are regular files. Symbolic links are never
  created by this materialization path.
<!-- planned-change:installable-template-trees -->
- **Content gate.** An absent or byte-different target is written; an identical
  target is left untouched.
<!-- change:installable-template-trees -->
- **Content gate.** Each template is rendered per the template-installation
  contract (`project/spec/feature/reconciliation/template-installation`) before
  comparison. An absent target, or one whose bytes differ from the rendered
  content, is written; an identical target is left untouched. An unresolved
  placeholder fails installation before any target is written.
<!-- /planned-change:installable-template-trees -->
- **Conflict posture.** A source or target whose filesystem type is not a
  regular file fails installation before that target is replaced or removed.
- **Activation order.** The complete template tree is materialized before the
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
<!-- planned-change:installable-template-trees -->
And a missing or byte-different target receives the template content
<!-- change:installable-template-trees -->
And a missing target, or one differing from the template's rendered content, receives that rendered content
<!-- /planned-change:installable-template-trees -->
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

## Known caveats

- Template removal is not a pruning contract. Materialization creates or
  refreshes declared targets; it does not delete a home file merely because a
  later checkout no longer carries a matching template.
