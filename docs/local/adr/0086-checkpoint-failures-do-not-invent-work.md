---
number: 86
date: 2026-09-11
description: Checkpoint evaluation blocks only on established maintenance actions and never substitutes generic work for an evaluation failure.
---

# Checkpoint Failures Do Not Invent Work — ADR

## Context

The checkpoint engine runs at an agent stop boundary and blocks that stop when it has established maintenance the agent still owes. Its outer failure guard instead converted any evaluation exception into a generic checkpoint instruction. A persistent failure therefore produced a blocking continuation unrelated to the failure, and the continuation reached another stop that repeated the same exception and block.

The choice was whether an incomplete evaluation should block conservatively, allow the stop while retaining the error as operational evidence, or expose the exception itself as an agent instruction.

## Decision

Only maintenance actions established by a completed checkpoint evaluation may block an agent stop. An evaluation failure is recorded through the structured logging boundary and produces no checkpoint reason, so the stop proceeds. The checkpoint never converts an exception into generic maintenance and never exposes arbitrary exception text as an instruction.

## Consequences

- Persistent evaluation failures cannot create self-sustaining checkpoint continuations.
- Every displayed checkpoint remains relevant to maintenance the evaluator actually established.
- Operational failures remain visible in structured logs without leaking internal exception detail into agent prompts.
- A checkpoint evaluation failure may allow an agent to stop while real maintenance remains undetected. The error record, rather than an invented prompt, is the truthful evidence available for recovery.

## Alternatives Considered

- Retain the generic blocking fallback. Rejected because it presents unestablished work and turns persistent failures into continuation loops.
- Block with the raw exception. Rejected because an arbitrary internal failure is not a maintenance contract and may expose sensitive or non-actionable detail.
- Reuse the last successful checkpoint result. Rejected because stale maintenance evidence can misattribute work across turns.
