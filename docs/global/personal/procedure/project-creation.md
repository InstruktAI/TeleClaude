---
description: Start a new project for the person when they ask their assistant to build something — shaped by the platform's new-build intake, placed in their own projects area without asking, and adopted as a project of their own.
activation_trigger: Use when the person asks you to build something new for them — a tool, an automation, a script, a small app — that no existing project of theirs already holds.
delivered_by:
  - personal-assistant-project-creation
---

# Project Creation — Procedure

## Required reads

@~/.teleclaude/docs/personal/policy/assistant-conduct.md

## Goal

Turn the person's request to build something into a project of their own:
shaped the way the platform shapes any new build, placed in their own projects
area without asking them where, and adopted so that it is an ordinary project
from its first moment and belongs to them
(`personal/spec/feature/personal-projects`).

## Preconditions

- You are the person's own assistant, in their own workspace
  (`personal/policy/assistant-conduct`).
- The request is for something new. A change to a project that already exists
  is ordinary work in that project, not this procedure.

## Steps

1. **Take it up as project work.** A request to build, automate, or make
   something is this procedure's work even when the person never says
   "project". Where it goes is settled below; never ask them.
2. **Shape it with the platform's new-build intake.** Load
   `sdlc/procedure/greenfield-intake` with its closure, together with the
   `sdlc` bundle it presumes, and run it with the person. They answer only what
   that intake marks as theirs; there is no separate assistant conversation.
3. **Place it.** Unless the person named a destination themselves, the
   project's folder is `projects/<name>/` in their workspace — the person home
   this session runs in — where `<name>` is the project's short kebab-case name.
   A destination the person names is their instruction; use it.
4. **Scaffold it** in that folder as the intake's flavor directs.
5. **Adopt it.** From the project folder, run `telec config project init --own`
   when the project sits anywhere in the person's own workspace — the default
   spot or one they named — so adoption gives it a repository of its own and
   records the person as its owner. For a destination the person named outside
   their own workspace, run `telec config project init` without `--own`. This is
   the initialization the intake's scaffolding step ends with; run it once.
6. **Hand it over.** Tell the person where the project is. Building it out is
   ordinary project work in that project from here.

## Outputs

- The intake's approved brief.
- An adopted project with its own history. Anywhere in the person's own
  workspace it is owned by them; at a destination they named outside it, you
  declare no owner.

## Recovery

- **Adoption is refused because another entry holds the identity.** The
  identity is the project's declared slug, else its declared name, else its
  folder name. Choose a more specific name and change whichever of those
  governs — the folder name only when the project declares neither — then adopt
  again.
- **Adoption is refused by clearance.** Stop and tell the person what was
  refused; do not route around it.
- **The intake's classification changes mid-conversation.** Follow the intake's
  own recovery; placement and adoption are unaffected.
