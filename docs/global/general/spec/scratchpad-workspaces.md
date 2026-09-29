---
description: Where the working files of design, brainstorming, analysis, investigation, and peer-convergence work live — one indexed, version-control-ignored directory per activity under the project's scratchpad/, never a harness- or session-private directory — and why that material stays non-authoritative, secret-free, and selectively promoted.
---

# Scratchpad Workspaces — Spec

## What it is

A scratchpad workspace is a disposable, project-local directory for related
working material produced during one exploratory activity. It gives humans and
agents a predictable place to collaborate without promoting drafts into the
documentation or artifact layers prematurely.

## Canonical fields

- Scratchpad workspaces live under `scratchpad/` at the root of the project's
  canonical checkout, which the adopting project excludes from version control.
- A harness-provided scratch directory or a session's temporary directory is
  not a scratchpad workspace, whatever the harness calls it: it is private to
  its session, invisible to every other session, and removed with the session.
- Each activity owns one directory named
  `scratchpad/YYYYMMDD-HHMMSS-<topic>/`, using the host's local time and a short
  kebab-case topic.
- Every activity directory carries an `index.md` whose content
  `general/procedure/scratchpad-workspace` defines. The procedure using the
  workspace names the other files. Related source, notes, checkpoints, and
  temporary renders stay together in that directory.
- Scratchpad content is disposable and non-authoritative. Durable docs,
  implementation, and workflow artifacts never cite it as a source of current
  truth.
- Secrets, credentials, personal data, and irreplaceable source material never
  enter a scratchpad.
- Promotion is selective: the owning procedure distills the agreed material
  into its durable authority. It never copies the workspace wholesale.
- Cleanup may remove any scratchpad whose index shows the activity finished
  and its useful content promoted. Retention is convenience, not lifecycle state.

## Allowed values

- Directory timestamp: `YYYYMMDD-HHMMSS`, all fourteen digits.
- Topic: lowercase kebab-case naming the activity, not an agent or tool.
- Contents: any files required by the owning procedure, provided they obey the
  non-authoritative and secret-free contract above.

## Known caveats

- A single throwaway file no other session will read — a one-off probe, a
  scratch render — may sit directly under `scratchpad/`. Material from design,
  brainstorming, analysis, investigation, or peer convergence, and any file that
  gains a successor or a second reader, belongs in an activity directory.
- A human agreement does not itself make scratchpad content current truth.
  Documentation and delivery rules still determine where and when the agreed
  result becomes authoritative.
