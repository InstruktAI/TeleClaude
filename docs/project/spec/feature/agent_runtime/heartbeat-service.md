---
description: Platform-owned one-shot heartbeat timers — armed by a session through the telec CLI, stored durably in the daemon, and fired as a typed wake frame through the existing session-input path.
delivered_by:
  - platform-heartbeat-service
---

# Heartbeat Service — Spec

## Required reads

- @docs/project/spec/domain/agent_runtime.md

## What it is

Agents idle for long stretches by design, and the heartbeat policy makes a
timer the precondition for every sustained work block. Today each agent CLI
implements that timer with its own runtime folklore, and every runtime has
produced its own silent death: reaped background tasks, foreground-blocking
waits, armings that do not survive turn close. An armed timer is
indistinguishable from a dead one from inside and outside the session alike,
so watches stall, departures never fire, and sessions read as dead while on
watch. One platform primitive makes arming inspectable, firing durable, and
the mechanism identical for every agent — cadence stays where it already
lives, in the briefs and state-machine instructions that name durations.

## Canonical fields

### Use cases

#### UC-HB1: A session arms a one-shot heartbeat

```gherkin
Given a live session invoking `telec heartbeat set --in <duration> --intent "<text>"`
When the duration is at least the 2-minute floor
Then a heartbeat row is created for the calling session with a unique id, armed_at, fire_at, and the verbatim intent
And the command returns the id
And the heartbeat belongs to the calling session only — no flag targets another session
```

#### UC-HB2: The floor refuses eager timers

```gherkin
Given a live session invoking `telec heartbeat set --in 10s --intent "poll"`
When the duration is below the 2-minute floor
Then nothing is created
And the refusal names the floor and that cadence is dictated by the governing brief
```

#### UC-HB3: A fire is one-shot and carries the fixed frame

```gherkin
Given an armed heartbeat whose fire_at has arrived
When the daemon fires it
Then the row is deleted before delivery is attempted
And a typed frame is injected through the existing session-input path carrying the heartbeat id, armed_at, the verbatim intent, and the fixed invalidation preamble: first check whether the human intervened after armed_at; if so, discard the encoded intent and re-evaluate; otherwise continue, correct course, or stop
And the frame carries no cadence guidance of any kind
```

#### UC-HB4: A busy session receives the fire as next input

```gherkin
Given a heartbeat fires while its session is mid-turn
When the injection path queues the frame
Then the frame arrives as the session's next input after the current turn
And no duplicate fire is created
```

#### UC-HB5: Fires into ended sessions are dropped

```gherkin
Given a heartbeat whose session has ended before fire_at
When the scheduler reaches it
Then the row is removed without delivery
And the drop is visible in daemon logs
```

#### UC-HB6: Session end revokes its heartbeats

```gherkin
Given a session with live heartbeats
When the session ends through any path
Then all its heartbeat rows are removed
And nothing later fires into the dead session
```

#### UC-HB7: The registry is listable and revocable by its owner

```gherkin
Given a session with live heartbeats
When it invokes `telec heartbeat list`
Then it receives its own heartbeats only: id, fire_at, intent
When it invokes `telec heartbeat revoke <id>` for its own heartbeat
Then that row is removed and never fires
```

#### UC-HB8: Heartbeats survive daemon restarts

```gherkin
Given armed heartbeats in the store
When the daemon restarts
Then the scheduler rescans the store on boot
And every heartbeat whose fire_at has not passed still fires on time
And every heartbeat whose fire_at passed during the outage fires once promptly after boot
```

#### UC-HB9: The working set is capped

```gherkin
Given a session already holding 3 live heartbeats
When it invokes `telec heartbeat set` again
Then nothing is created
And the refusal names the cap and points at `telec heartbeat list` and `revoke`
```

#### UC-HB10: Sessions expose their next wake

```gherkin
Given a session with at least one live heartbeat
When the sessions listing is read
Then the session row carries next_heartbeat_at
And a session with no live heartbeat carries none — making on-watch and unarmed visibly different states
```

## Known caveats

- One-shot only, permanently: re-arming is the agent's decision at fire time,
  per the heartbeat policy. No recurring or cron form exists on this surface.
- Cadence is never this feature's voice: durations come from the governing
  briefs and state-machine instructions; the CLI help and the fire frame carry
  no interval advice.
- Self-arm only: no session arms, lists, or revokes another session's
  heartbeats through this surface.
- Free-text intent: the platform stamps and transports it, never validates it.
