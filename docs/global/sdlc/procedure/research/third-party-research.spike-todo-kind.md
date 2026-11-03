---
activation_trigger: Use when entering unfamiliar third-party territory, or about to declare
  something impossible, require a fork, or invent a custom mechanism — scan prior
  art first (general/principle/grounding).
description: 'Research third-party behavior: find what is already recorded, gather authoritative
  sources, verify live with throwaway resources where it matters, and record verified facts
  with their verification apart from hypotheses.'
visibility: public
role: third-party-researcher
parameters:
  - name: brief
    required: true
    rest: true
dispatch:
  agent: [claude, codex, gemini, deepseek]
  thinking_mode: slow
---

# Third-Party Research — Procedure

## Goal

Answer a question about one upstream party's behavior with facts that are
verified, and record them as third-party documentation every later agent can
rely on (`general/spec/third-party-docs`). Agent artifacts never cite the
upstream sources directly; they cite the third-party documentation.

The procedure also serves the **prior-art scan** the grounding principle
requires before designing unfamiliar infrastructure or concluding a hard
problem is unsolved. Findings that inform only one design or debugging
decision go into that decision's artifact — the architecture's Prior-art &
adopt-vs-build section, or the diagnosis — rather than into third-party
documentation; a third-party snippet is written only when it earns its place
(`general/policy/snippet-value-contract`).

## Preconditions

- The brief names a question and the upstream party it concerns. A spike's
  `task-plan` carries both (`sdlc/spec/todo-kind-spike`).

## Steps

<!-- @include: docs/snippets/step-role-read.md -->

1. **Define the brief.** State the question in the upstream party's terms and
   what answers it. A brief spanning several upstream parties is split into
   one brief per party; a comparison between them belongs to the artifact that
   asked, not to any party's documentation.

2. **Read what is already recorded.** Search the project and the global
   third-party documentation (`telec docs index --third-party`). A fact recorded
   with its verification that answers the question ends the research: return
   it. A fact recorded without its verification is a lead to verify, not an
   answer.

3. **Gather authoritative sources.** Prefer the party's official documentation,
   reference and changelog, read at the current version; use Context7 and web
   search, and Firecrawl only when those fail. Record every source used.

4. **Verify live where it matters.** Where the documentation is silent,
   ambiguous or contradicted, or where the waiting decision turns on the exact
   behavior, observe it: create a throwaway resource, exercise the behavior,
   capture the evidence — the request and response, the command and its
   output — and remove the resource. Never test against live data or a
   resource you did not create. Before creating a resource, record what you
   are about to create and the identity you will find it by where your run
   keeps its record (a spike's `log`), then record its removal there.

5. **Separate facts from hypotheses.** A fact is either read from a cited
   authoritative source or observed in a live test you ran. Everything else —
   an inference, a pattern from another party, a recollection — is a
   hypothesis and is labelled so.

6. **Record the findings.** Write each fact into the party's third-party
   documentation at the placement `general/spec/third-party-docs` gives, with
   when and how it was verified, a **Sources** section and a **Gaps/Unknowns**
   section for what stayed unverified. Platform-specific implications and
   recommendations go to the artifact that asked, never into the party's
   documentation. When the research runs as a spike, the exploration trail —
   hypotheses, evidence, what was tried — goes to the exploration home
   (`general/spec/exploration-home`).

## Outputs

- Third-party documentation whose facts each state when and how they were
  verified, with Sources and Gaps/Unknowns.
- For a prior-art scan feeding one decision: the findings in that decision's
  artifact.
- When run as a spike: the exploration trail in the exploration home.

## Recovery

- **No authoritative source and no way to observe the behavior.** Write no
  fact. Record the question as unanswered, with what was tried, in the
  asking artifact or the spike's `log`.
- **A live test would need live data or a resource you cannot create and
  remove yourself.** Do not run it. Record the behavior as unverified and why.
- **Recorded documentation contradicts what you observed.** Correct it with the
  observation and its evidence; the older claim does not stand beside it.
