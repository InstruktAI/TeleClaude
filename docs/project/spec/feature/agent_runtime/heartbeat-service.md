---
description: Platform-owned one-shot heartbeat timers — armed by a session through the telec CLI, stored durably in the daemon, and handed to the existing session-input delivery surface when due.
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
And CLI help states the floor but recommends no heartbeat cadence
```

#### UC-HB3: A fire is one-shot and carries the fixed frame

```gherkin
Given an armed heartbeat whose fire_at has arrived
When the daemon fires it
Then the daemon submits a typed frame through the existing session-input delivery surface carrying the heartbeat id, armed_at, the verbatim intent, and the fixed invalidation preamble: first check whether the human intervened after armed_at; if so, discard the encoded intent and re-evaluate; otherwise continue, correct course, or stop
And the heartbeat is consumed once that surface accepts the handoff — it never fires twice and no duplicate frame is ever produced
And the frame carries no cadence guidance of any kind
```

#### UC-HB4: Message delivery retains its existing contract

```gherkin
Given a heartbeat becomes due for a live session
When the daemon submits its typed frame
Then it uses the platform's existing session-input delivery surface
And handoff success or failure follows that surface's existing return contract
And the heartbeat service adds no runtime-specific delivery path or success mechanism
And it creates no additional guarantee about delivery retry, runtime wake-up, or processing confirmation
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
And every heartbeat whose fire_at is still in the future retains its scheduled fire time
And every heartbeat overdue at recovery — one whose fire_at passed during the outage, or one that fell due but whose frame was not yet accepted by the input path when the daemon stopped — retries its handoff promptly after boot
And once due, a heartbeat handoff is accepted once by the existing input path — never silently lost and never submitted again after acceptance
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

#### UC-HB11: Re-arming atomically replaces an active heartbeat by id

```gherkin
Given a calling session owns a live heartbeat identified by `<id>`
When it re-arms that heartbeat with a replacement duration and intent
Then the replacement is one atomic operation
And `<id>` remains the heartbeat's identity in the registry
And armed_at, fire_at, and intent are replaced together
And exactly one live row exists for that heartbeat
And the superseded deadline can never fire after the replacement succeeds
And replacing an id that is no longer live creates nothing and reports that it cannot be replaced
```

## Known caveats

- One-shot firing only, permanently: an active heartbeat may be re-armed
  atomically by its id before it fires; a consumed heartbeat is not replaceable.
  No recurring or cron form exists on this surface.
- The heartbeat id is its registry and replacement identity. There is no
  separate semantic name and free-text intent is never used as identity.
- Cadence is never this feature's voice: durations come from the governing
  briefs and state-machine instructions; the CLI help and the fire frame carry
  no interval advice.
- Self-arm only: no session arms, lists, or revokes another session's
  heartbeats through this surface.
- Free-text intent: the platform stamps and transports it, never validates it.
- Message delivery stays outside this feature's ownership. The service submits
  the typed frame and follows the existing session-input surface's return
  contract. That contract does not establish runtime wake-up or processing
  confirmation; any defect there is separate delivery work.
- The fire is one-shot across interruptions too: an interrupted handoff
  retries at recovery until the existing input path accepts it once — never a
  silent loss, never another submission after acceptance. What happens after
  acceptance remains entirely under the existing message-delivery contract.
