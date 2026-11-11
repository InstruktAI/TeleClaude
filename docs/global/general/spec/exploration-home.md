---
description: "The exploration home `docs/explore/` holds a project's committed exploration trails — research reports and investigation trails — read as plain files and never a contract or a taxonomy snippet home."
delivered_by: [spike-todo-kind]
---

# Exploration Home — Spec

## What it is

The exploration home is the `docs/explore/` directory of a project. It keeps
the trail of an investigation after the investigation ends: a research report,
an incident trail, or the exploration behind a spike
(`sdlc/spec/todo-kind-spike`). A later session reads it to resume or reuse an
investigation without repeating it.

## Canonical fields

- **What it holds.** One Markdown file per subject explored, named for that
  subject. A file holds the brief or question, the hypotheses, the evidence
  with its sources, what was tried and with what result, and the open
  questions. Hypotheses and verified findings are labelled as such, and each
  entry is dated.
- **What it is not.** It is not a taxonomy snippet home: its files carry no
  frontmatter and follow no snippet schema, they are not indexed, not published
  and not served by `telec docs`, and no snippet names one as a Required read. It
  is not a contract: a fact found there becomes something agents rely on only
  once it is recorded in third-party documentation (`general/spec/third-party-docs`)
  or in the contract that owns it. It is not a scratchpad: it is committed and
  durable (`general/spec/scratchpad-workspaces`).
- **How agents read it.** As plain files under `docs/explore/`. Its content
  carries no pending material, so nothing in it needs the filtering `telec docs`
  applies; an agent reads it as history and evidence, never as current
  contract.
- **How it is written.** An entry is appended to the subject's file, or a new
  file is created for a new subject, and committed under `general/policy/commits`.
