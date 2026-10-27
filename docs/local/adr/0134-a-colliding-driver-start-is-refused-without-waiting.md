---
visibility: public
number: 134
date: 2026-10-26
description: A lifecycle orchestrator start that finds another start of the same todo inside the admission section is refused at once, naming the session that start is creating or claiming, instead of waiting for it.
---

# A Colliding Driver Start Is Refused Without Waiting — ADR

## Context

ADR-0133 serializes lifecycle orchestrator starts for one todo on one computer
with an in-process critical section across the live-holder check and the
creation or claim it admits. It lets a start wait while another start of the
same todo is inside the section, bounded below the callers' request deadline.

The callers of the session create doors wait on one HTTP response under a fixed
client timeout that starts before the request is sent. Before a start reaches
the section it runs the existing project-wide guard, and after the section it
runs the session creation; neither has a bound. A wait for the section spends
the same response window, so under contention a request that would have fitted
its deadline can now time out with its outcome unknown, and a lifecycle runner
pass whose start times out fails, although a pass that loses a start must count
the todo as driven and continue.

A start that collides with another start of the same todo is a concurrent start
of that todo: the outcome required is that it does not become a second driver.
Waiting for the start ahead of it almost always ends with that start recorded as
the holder and the waiter refused anyway. Session ids are known before a session
is created, and an adopting caller is an existing session, so the start inside
the section can be named before its ownership fact exists.

## Decision

A start that finds the admission section for its todo held by another start does
not wait: it is refused at once as busy, naming the session that other start is
creating or claiming. While a start holds the section, the section remembers that
session id in memory and releases it when the start leaves. A start that finds
the section free takes it at once, as ADR-0133 decides. Nothing about the section
is recorded durably.

## Consequences

- The section adds no wait to any request: a start's response time is its guard,
  the holder re-check and its creation or claim, as without contention.
- Every losing start names a session — the recorded holder, or the start still
  being decided — so its caller and a lifecycle runner pass can treat the todo as
  driven without reading a timeout.
- A start refused because it collided with a start that later fails is not
  admitted in that start's place. Its caller starts again; the lifecycle runner
  does so on a later pass.
- The busy refusal is a distinct outcome from the holder conflict at the create
  doors, so callers that must tell them apart do so without parsing text.

## Alternatives Considered

- **A bounded wait from the start of the request.** Measuring the bound from
  when the request began counts the guard's time, but still spends the caller's
  response window on the wait, and the work after the section remains unbounded;
  it cannot keep a contended request inside its deadline.
- **A fixed bounded wait** (ADR-0133's consequence). Rejected for the same reason:
  the bound limits only acquisition, not the response.
- **Waiting without a bound.** Rejected: a start can hold the section while it
  writes to a remote store, so a waiter's response would depend on another
  request's provider latency.
