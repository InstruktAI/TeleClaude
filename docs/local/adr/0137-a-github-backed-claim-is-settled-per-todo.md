---
visibility: public
number: 137
date: 2026-10-27
description: A computer answers for a claimed session only as the driver of that todo, a release for a todo is ordered by the releasing computer's admission section until it can no longer reach the master, the master is the only writer while a start can be admitted, and reactivating a removed todo restores the claim its removal set aside.
---

# A GitHub-Backed Claim Is Settled per Todo — ADR

## Status

Superseded by ADR-0142

## Context

ADR-0135 has the master admit every orchestrator start of a todo in a project
on the GitHub workflow store, and judge a claim by asking the computers the
platform knows whether the claimed session is theirs: held while it is open or
starting, ended once it is closed. ADR-0136 makes the master the only writer of
such a claim: other computers ask it to release a claim for a session they ran,
and the master clears only while the claim still names that session. It also
says every claim write is the master's, while leaving the clears of delivery,
removal and other transitions as they were.

Three cases fall between these rules.

- An in-place start claims a todo for a session that already exists. When the
  start gives up after the master recorded the claim — its caller stopped
  waiting — the session stays open without driving the todo. Judged by whether
  it is open, it holds the claim for as long as it lives, and no orchestrator
  is ever started for the todo.
- A session that releases a todo and later claims it again carries the same
  session id both times. A release that reaches the master after the new
  admission still finds the claim naming that session, and clears the claim of
  a live driver.
- A removal that a caller forces sets the claim aside in its removal record;
  reactivating the todo discards it. A driver still running on another
  computer is then held by nothing the master can judge, and a later start is
  admitted beside it.

## Decision

- **A computer answers for a session as the driver of one todo.** Asked about
  a claimed session for a todo, a computer answers that it holds the todo while
  that session is open, not closing, and carries the lifecycle driver role with
  that todo as its working slug, or while a start of that session for that
  todo is inside its admission section. It answers that the claim has ended
  when it ran that session and neither holds; and that the session is not its
  own when it has no record of it and no start of it.
- **A release is ordered by the releasing computer's section.** A computer
  issues a release for a todo only from inside its own admission section for
  that todo, and keeps the section until the master has answered or the
  release's relay deadline has passed. The relay refuses a request that reaches
  its destination after its deadline, so no release from that computer can
  reach the master after a later start of the todo on that computer has been
  admitted.
- **The single writer covers todos a start can be admitted for.** ADR-0136's
  rule applies to every claim write of a todo an orchestrator start can be
  admitted for. Delivering or removing a todo clears or sets aside its claim as
  part of that transition, because no start is admitted for a delivered or
  removed todo.
- **Reactivation restores the set-aside claim.** Reactivating a removed todo
  in a project on the GitHub store restores the claim its removal set aside, so
  the master judges it before admitting any start. A removal that a caller
  forced keeps its meaning: it removes the todo whatever holds it, and does
  not end that holder.

## Consequences

- A start that gave up leaves a claim the master clears once the session's
  computer answers that the session does not drive the todo, whether or not
  the session is still open.
- A session that releases a todo and claims it again cannot lose its new claim
  to its own earlier release; another start of that todo on its computer is
  refused as busy while the release is unsettled.
- A forced removal followed by reactivation cannot let a second orchestrator
  start beside one still running on another computer.
- Releasing a claim keeps the releasing computer's section for the todo busy
  for at most the release's relay deadline.
- ADR-0135 is superseded in part: a computer's answer is about the session
  driving the todo, not about the session being open. ADR-0136 is superseded
  in part: its single writer is scoped as stated here, and releases are
  ordered by the releasing computer's section.

## Alternatives Considered

- **Judge a session held while it is open.** An in-place start that gave up
  holds its todo for the life of its caller.
- **Mark each admission with a generation the release must name.** It needs a
  new field in the claim, which older releases cannot read (ADR-0135).
- **Wait for every release to complete before answering its caller.** It puts
  the master's GitHub work back inside session end, housekeeping and unclaim,
  and still leaves a release whose answer is lost unordered.
- **Refuse a forced removal while a claim is held on another computer.** It
  takes away the override a caller forces removal for, where restoring the
  claim keeps both.
