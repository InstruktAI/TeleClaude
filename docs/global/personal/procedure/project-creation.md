---
description: Start a new project for the person when they ask their assistant to build something — shaped by the platform's new-build intake, created in their own projects area without asking, scaffolded and converged.
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
2. **Build it with the platform's new-build intake.** Load
   `sdlc/procedure/greenfield-intake` with its closure, together with the
   `sdlc` bundle it presumes, and run it with the person end to end. They
   answer only what that intake marks as theirs; there is no separate assistant
   conversation. The intake's own step creates the project with
   `telec config project create <name>`, scaffolds it and converges it. In the
   person's session that lands in their own projects area, owned by them; add
   `--company <slug>` only when they ask for a company project. Never pick a
   folder yourself.
3. **Hand it over.** Tell the person where the project is. Building it out is
   ordinary project work in that project from here.

## Outputs

- The intake's approved brief.
- A created, scaffolded and converged project with its own history, owned by the
  person, or by their company when asked.

## Recovery

- **`create` refuses the name.** The name is taken on this computer, or is not
  a valid slug. Choose a more specific name and create again.
- **`create` is refused by clearance.** Tell the person what was refused and
  why — usually a company they are not a member of — and offer their own
  projects area instead. Never route around the refusal.
- **The person wants it somewhere outside their home.** A project outside every
  home is a platform project, created only by a platform administrator. Tell
  them so, and offer their own projects area.
- **The intake's classification changes mid-conversation.** Follow the intake's
  own recovery; creation is unaffected.
