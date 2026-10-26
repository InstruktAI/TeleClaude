---
description: Dispatched bug-diagnosis peer procedure. Investigate independently, establish the causal mechanism, and author the diagnosis artifact without taking over prepare orchestration.
visibility: internal
role: diagnoser
parameters:
  - name: slug
    required: true
dispatch:
  agent: [codex, claude, gemini, deepseek]
  thinking_mode: slow
---

# Peer Bug Diagnosis — Procedure

## Required reads

- @~/.teleclaude/docs/general/policy/human-involvement-recording.md
- @~/.teleclaude/docs/sdlc/procedure/debugging.md

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
- This session carries the diagnosis prepare-author capability while the prepare-driving
  session remains the todo's lifecycle claimant. Artifact authorship requires no todo claim
  or temporary lease.

## Steps

<!-- @include: docs/snippets/step-role-read.md -->

1. Read `telec todo show {slug}` and the `input` artifact. Use the creation record to locate
   the organic trigger and its evidence surface. `human_involved` records participation, not
   authorship or ratification of every detail. Treat agent-added causes, remedies, numeric
   bounds, and adjacent scope as hypotheses.
2. Treat the symptom as a real defect until evidence proves otherwise. Follow the debugging
   procedure: reproduce where possible, perform the unconditional provenance check, bisect
   the failing path, and isolate one falsifiable causal mechanism. Label synthetic
   reproduction and state any gap from the organic path.
3. Apply the debugging procedure's operation-outcome and failure-handling distinction.
   Record the operation, the source and applicability of its expected outcome, and the
   evidence supporting the investigation boundary. Trace backward to the earliest violated
   contract inside that boundary. Record the complete minimal causal set, including
   enabling conditions such as races, ordering, or omitted handling. When the root is a
   shared contract, enumerate every producer, entry path, and consumer in the boundary and
   classify each from observed evidence.
   Account for the reported occurrences individually or in evidence-supported causal
   groups. State which transitions a reproduction supports and which remain unsupported
   for the reported occurrences. Record unexplained occurrences and the missing evidence
   without representing them as explained by the reproduction.
4. Write `diagnosis` with `telec todo artifacts write {slug} diagnosis <content>`. Keep
   observations separate from the argument that cites them, and include:
   - **Status** — `Draft`, `Settled`, or `Unresolved`.
   - **Symptom** — expected versus observed behavior, the expected outcome's source and its
     applicability to the observed conditions, organic trigger, reproduction status, and
     any synthetic-to-organic gap.
   - **Provenance** — exactly `Regression`, `Latent`, or `Provenance not established`, with
     the evidence required by the debugging procedure.
   - **Observations** — what was seen, how it was obtained, and why it was inspected.
   - **Causal trace** — every transition, its carrying observations, its falsifier, comparable
     near misses, occurrence coverage, and the implementation census when the root is shared.
   - **Alternatives** — the strongest credible rival and the discriminating check actually
     run, or the reason no credible rival survives statement.
   - **Root cause** — the minimal causal set and its counterfactual, with no fix.
   - **Mechanism** — the code shape behind the root cause, stated as the debugging
     procedure requires: decidable at one site by reading it. When a governing design or
     decision record prescribes it, that contract by id, and whether its design's
     `Failure modes` already record this failure.
   - **Family census** — the two searches the debugging procedure bounds this lane to,
     and every site they found, each marked matching, not matching, or undecided.
   - **Attack record** — initially empty or marked pending; the peer updates it when the
     prepare-driving session later challenges the written mechanism.
5. Write the `diagnosis` artifact, then go idle for the prepare-driving session's response. If the prepare-driving session returns an evidence gap or
   challenge, gather the missing evidence, revise the artifact yourself, and update the
   Attack record with the challenged transition, evidence, and resulting movement. The peer
   keeps the pen for every diagnosis version.

## Outputs

- A `diagnosis` artifact whose observations are independently auditable and whose causal
  trace either establishes the root cause or states precisely what remains unresolved.
- No production-code, test, worktree, commit, fix, verification prescription, lifecycle
  stamp, todo transition, or child session.

## Discipline

You are the dispatched diagnosis peer, not the prepare-driving session. Do not triage,
dispatch another worker, interrogate your own artifact, stamp the diagnosis, or advance the
prepare state machine. Investigate independently, write `diagnosis`, prescribe no fix, and
wait for the driver to challenge or accept the evidence.

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
- If the artifact-author boundary refuses the write, stop and report the authorization
  failure to the driving session rather than writing through another surface. Do not seek a
  todo claim, temporary lease, or alternate write path.
