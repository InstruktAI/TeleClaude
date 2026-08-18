---
description: Dispatched bug-diagnosis peer procedure. Investigate independently, establish the causal mechanism, and author the diagnosis artifact without taking over prepare orchestration.
visibility: internal
---

# Peer Bug Diagnosis — Procedure

## Required reads

- @~/.teleclaude/docs/general/policy/human-involvement-recording.md
- @~/.teleclaude/docs/software-development/procedure/debugging.md

## Goal

Independently investigate a reported bug and write the `diagnosis` artifact that the
prepare-driving session will interrogate. The peer establishes why the observed behavior
occurs and stops at the causal mechanism; it does not triage the todo landscape, dispatch
another session, prescribe a fix, stamp the diagnosis, or advance the prepare state machine.

## Preconditions

- The prepare-driving session dispatched this session for a todo whose kind is `bug` and
  whose lifecycle phase is `DIAGNOSE`.
- `telec todo artifacts read {slug} input` contains the reported symptom and discovery
  context.
- The dispatch lease grants this session sole write authority for the `diagnosis` artifact.

## Steps

1. Read `telec todo show {slug}` and the `input` artifact. Use the creation record to locate
   the organic trigger and its evidence surface. `human_involved` records participation, not
   authorship or ratification of every detail. Treat agent-added causes, remedies, numeric
   bounds, and adjacent scope as hypotheses.
2. Treat the symptom as a real defect until evidence proves otherwise. Follow the debugging
   procedure: reproduce where possible, perform the unconditional provenance check, bisect
   the failing path, and isolate one falsifiable causal mechanism. Label synthetic
   reproduction and state any gap from the organic path.
3. Trace backward to the earliest violated contract inside the stated system boundary.
   Record the complete minimal causal set, including enabling conditions such as races,
   ordering, or omitted handling. When the root is a shared contract, enumerate every
   producer, entry path, and consumer in the boundary and classify each from observed
   evidence.
4. Write `diagnosis` with `telec todo artifacts write {slug} diagnosis <content>`. Keep
   observations separate from the argument that cites them, and include:
   - **Status** — `Draft`, `Settled`, or `Unresolved`.
   - **Symptom** — expected versus observed behavior, organic trigger, reproduction status,
     and any synthetic-to-organic gap.
   - **Provenance** — exactly `Regression`, `Latent`, or `Provenance not established`, with
     the evidence required by the debugging procedure.
   - **Observations** — what was seen, how it was obtained, and why it was inspected.
   - **Causal trace** — every transition, its carrying observations, its falsifier, comparable
     near misses, and the implementation census when the root is shared.
   - **Alternatives** — the strongest credible rival and the discriminating check actually
     run, or the reason no credible rival survives statement.
   - **Root cause** — the minimal causal set and its counterfactual, with no fix.
   - **Attack record** — initially empty or marked pending; the peer updates it when the
     prepare-driving session later challenges the written mechanism.
5. Report completion and wait. If the prepare-driving session returns an evidence gap or
   challenge, gather the missing evidence, revise the artifact yourself, and update the
   Attack record with the challenged transition, evidence, and resulting movement. The peer
   keeps the pen for every diagnosis version.

## Outputs

- A `diagnosis` artifact whose observations are independently auditable and whose causal
  trace either establishes the root cause or states precisely what remains unresolved.
- No production-code, test, worktree, commit, fix, verification prescription, lifecycle
  stamp, todo transition, or child session.

## Discipline

This session is the dispatched diagnosis peer, never the prepare driver. Do not perform
triage, dispatch another diagnoser, interrogate your own artifact, stamp a verdict, or call
`telec todo prepare`; those acts belong to the driving session. Follow evidence backward to
the earliest violated contract, write only what the observations carry, and stop before a
fix or verification approach.

## Recovery

- If no cause grounds, write `Status: Unresolved` with the verified observations, competing
  mechanisms, and the observation that would separate them; do not invent a likely cause.
- If the behavior is correct, record that conclusion and its evidence in `diagnosis`; the
  driving session owns reclassification, suppression, or closure.
- If the cause is a process-design gap, diagnose and report it without changing the process;
  the driving session owns the authority escalation.
- If the artifact lease lapses or refuses the write, stop and report the boundary failure to
  the driving session rather than writing through another surface.
