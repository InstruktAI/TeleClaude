---
description: 'The terms that ground a claimed defect — occurrence, dangerous path, reachable condition — shared by filing, triage, building, and review.'
visibility: 'public'
---

# Defect Evidence — Concept

## What

These terms carry the evidence for a claimed defect. Every contract that judges
a defect claim — filing it, triaging it, building around it, or raising it in
review — uses them.

- **Occurrence** — the defect happened in real use. A person or system acting
  for its own purpose produced the triggering input and state, and an address a
  reader can open shows it: a log record, a delivered message, a session
  transcript, a person's account of what they experienced. Diagnosis calls this
  the organic trigger. Input or state that an agent's test, probe, smoke run, or
  reproduction produced is synthetic, whatever that agent intended; it can
  reproduce an occurrence but is never one.
- **Dangerous path** — a concrete path to a defect that has not occurred. It
  names who acts, through which surface, holding what access, doing what, and it
  ends in a consequence that meets the safety gate's bar in
  `general/policy/human-contract`: material, hard-to-reverse exposure of a
  human-owned asset. Hard-to-reverse is judged by what is lost, leaked, or done
  in someone's name before anyone can intervene. A transient, self-clearing, or
  cosmetic consequence does not meet the bar, and neither does a state that
  only waits, losing nothing, until someone notices and undoes it. The path
  takes one of two forms:
  - **Ordinary use** — every step is an act the actor performs through the
    surface's ordinary operation, with real-use inputs.
  - **Deliberate misuse** — an actor whose relationships grant it no reach to
    the exposed asset constructs inputs that reach or impair that asset. This is
    the only form in which constructed inputs count. An agent acting on such an
    actor's input is the surface of the path, not its actor. Agents, and any
    party acting within the reach it was granted, are otherwise trusted
    (`general/principle/trust-and-guardrails`) and are never this actor.

  "Someone could" names no actor and is not a path.

- **Family site** — a site a settled diagnosis's family census marks as matching
  its mechanism (`sdlc/procedure/debugging`). It carries that diagnosis's
  occurrence as its evidence, and the session governing the diagnosis files it.

- **Real-use input** — an input real use produces, shown rather than asserted:
  an observed instance of it in real use, even one that triggered no defect, or
  a producer the code actually receives input from that emits it. The
  theoretical range of an input's type is not evidence that real use produces
  any particular value in it.
- **Reachable condition** — a condition that has occurred, that real-use input
  produces, or that a dangerous path reaches. Any other condition is
  unreachable, including one real use might produce but no shown real-use input
  or dangerous path reaches. Having been produced so far only by tests decides
  nothing either way; for code that has not shipped, a producer it actually
  receives input from shows its real-use input.

## Why

A defect that only synthetic input produces changes nothing anyone experiences.
Reporting it spends a diagnosis, and handling it adds code that defends against
nothing; such code accumulates into a codebase shaped by conjecture. Each term
ties a claim to something a reader can check — an address, an observed input, a
named actor, an access, an act — rather than to how plausible the claim sounds,
so two agents reading the same claim classify it the same way. A report can
always assert a malicious actor or a user who "pastes anything"; only shown
evidence names one.
