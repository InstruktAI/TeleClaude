---
description: Every TeleClaude configuration schema is published once per machine into
  a real directory in the TeleClaude home, from the canonical checkout's current source,
  and no repository carries a schema copy.
---

# Config Schema Publication — Spec

## What it is

A machine publishes the JSON Schemas that describe TeleClaude's configuration
files into one place: the TeleClaude home's schema directory. The tier schemas
are generated from the models the runtime validates against
(`teleclaude/config/schema_export.py`); the MCP registry schema is authored in
the MCP context's source and published beside them. Publication is the only
writer of that directory's schema files, and no repository carries a schema
file.

The computer schema describes the authored machine document, including its
declaration fields, defaultable sections, environment references, agent
inventory and named remote computers. Runtime-derived fields are excluded.
Publication uses the config context's input projection of its canonical models;
the runtime remains the authority for cross-field and operational validation.
Editor suggestions follow effective field editability tiers
(`local/projects/teleclaude/policy/config-public-surface`); internal fields
remain valid where the runtime accepts them but are not suggested for editing.

A home-tree configuration file references the published schemas directly; a
project configuration reaches them through its root's machine-local schema
link (`local/projects/teleclaude/spec/feature/reconciliation/project-plumbing-convergence`). The
reference each file carries is fixed by its tier
(`local/projects/teleclaude/spec/feature/config/tier-declaration`).

## Canonical fields

- **Target.** The TeleClaude home's schema directory, a real directory.
- **Content.** Every configuration schema, including the MCP registry's.
- **Content gate.** A schema file is rewritten only when its content differs
  from what is published; a run with nothing changed writes nothing.
- **Interim link.** A symbolic link at the target is replaced by a real
  directory; removing a link discards no content.
- **Conflict.** Any other non-directory entry at the target fails publication,
  names the target, and leaves it untouched.

- **Triggers.** The install act that makes a release active publishes from that
  release's source
  (`local/projects/teleclaude/spec/feature/reconciliation/installed-releases`).
  A commit in any project, a project checkout and a worktree publish nothing,
  so the home describes the code the machine runs.

### Use cases

#### UC-CSP1: Machine installation publishes every configuration schema into the home

#### UC-CSP2: Publication leaves current schemas untouched

#### UC-CSP3: A configuration model change on main refreshes the published schemas

#### UC-CSP4: An interim schema link is replaced by a real directory

#### UC-CSP5: A conflicting schema path fails publication untouched

#### UC-CSP6: Work under construction never reaches the published schemas

## Known caveats

- A machine that has not yet received a model change keeps the schemas of the
  code it runs; editors on that machine validate against those.
- A configuration file on a machine without TeleClaude, or in a project that is
  not adopted, carries a reference that resolves nowhere. The reference is
  advisory: loading reads the tier declaration alone.
