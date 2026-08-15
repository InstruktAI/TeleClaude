---
description: Convention for disposable, activity-scoped working material that must not become a source of truth.
---

# Scratchpad Workspaces — Spec

## What it is

A scratchpad workspace is a disposable, project-local directory for related
working material produced during one exploratory activity. It gives humans and
agents a predictable place to collaborate without promoting drafts into the
documentation or artifact layers prematurely.

## Canonical fields

- Scratchpad workspaces live under `scratchpad/`, which the adopting project
  excludes from version control.
- Each multi-file activity owns one directory named
  `scratchpad/YYYYMMDD-HHMMSS-<topic>/`, using the host's local time and a short
  kebab-case topic.
- The procedure using the workspace defines its filenames. Related source,
  notes, checkpoints, and temporary renders stay together in that directory.
- Scratchpad content is disposable and non-authoritative. Durable docs,
  implementation, and workflow artifacts never cite it as a source of current
  truth.
- Secrets, credentials, personal data, and irreplaceable source material never
  enter a scratchpad.
- Promotion is selective: the owning procedure distills the agreed material
  into its durable authority. It never copies the workspace wholesale.
- Cleanup may remove any scratchpad whose activity is finished and whose useful
  content has been promoted. Retention is convenience, not lifecycle state.

## Allowed values

- Directory timestamp: `YYYYMMDD-HHMMSS`.
- Topic: lowercase kebab-case naming the activity, not an agent or tool.
- Contents: any files required by the owning procedure, provided they obey the
  non-authoritative and secret-free contract above.

## Known caveats

- Single throwaway files may remain directly under `scratchpad/`; the activity
  directory convention applies when the work has multiple related files or is
  shared between participants.
- A human agreement does not itself make scratchpad content current truth.
  Documentation and delivery rules still determine where and when the agreed
  result becomes authoritative.
