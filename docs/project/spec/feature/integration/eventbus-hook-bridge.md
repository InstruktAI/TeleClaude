---
description: "Subscribes to the integration service's internal event bus, normalizes each event into a HookEvent, runs it through the Contract matcher, and dispatches to internal handlers or webhook subscriber endpoints."
visibility: 'public'
---

# EventBus Hook Bridge — Spec

## Required reads

- @~/.teleclaude/docs/software-development/principle/domain-driven-design.md
- @~/.teleclaude/docs/software-development/spec/domain-spec.md
- @docs/project/spec/domain/integration.md

## What it is

The bridge that connects the in-process event bus (where domain events
like session-started, agent events, agent activity, and errors flow) to
the contract / matcher dispatch path (which fans out to internal handlers
and external webhook subscriber endpoints). On integration service
startup the bridge subscribes to a fixed set of event-bus event types;
on each fired event it computes a canonical `source` and `type`, packs
identifying properties (session id, agent event type, tool name,
severity, error source, error code) and a payload (raw agent event data,
error message), wraps it as a hook event, and calls the hook dispatcher.

The bridge is the OUTBOUND side of the integration boundary: it makes
the integration service's internal domain events available as routable
hook events that subscribers (contracts) can react to via internal
handlers or external webhook deliveries.

## Canonical fields

### Use cases

#### UC-EB1: Session lifecycle event becomes a session.\* hook event

```gherkin
Given the event bus emits a session-started event with a session-lifecycle context for session "sess-1"
When the bridge handler runs
Then it recognizes the lifecycle context
And properties = {session_id: "sess-1"}
And hook type = "session.started" (derived as "session." + the event-type suffix)
And source = "system" (from the source-map for session events)
And a hook event is built with the current timestamp
And the hook dispatcher is invoked
And any contract matching source="system" / type pattern "session.*" / property session_id="sess-1" receives the event
```

#### UC-EB2: Agent event becomes agent.<event_type> hook event

```gherkin
Given the event bus emits an agent event with session "s1", event type "prompt_submitted", and a raw data payload
When the bridge handler runs
Then properties = {session_id: "s1", agent_event_type: "prompt_submitted"}
And hook type = "agent.prompt_submitted"
And source = "agent"
And if the data carries an original hook payload, that payload becomes the hook event payload
And the dispatcher is invoked
```

#### UC-EB3: Tool use activity carries tool_name property

```gherkin
Given the event bus emits an agent-activity event for a tool-use activity on session "s1" with tool name "Bash"
When the bridge handler runs
Then properties = {session_id: "s1", agent_event_type: "tool_use", tool_name: "Bash"}
And hook type = "agent.activity.tool_use"
```

#### UC-EB4: Error context translates to error.<severity> with payload message

```gherkin
Given the event bus emits an error event with severity "error", error source "hook_receiver", code "HOOK_INVALID_JSON", message "bad json"
When the bridge handler runs
Then properties = {session_id, severity: "error", error_source: "hook_receiver", error_code: "HOOK_INVALID_JSON"}
And hook type = "error.error"
And payload = {message: "bad json"}
And the dispatcher is invoked
```

#### UC-EB5: Dispatch failure is logged but does not raise

```gherkin
Given the hook dispatcher raises (matcher fault, handler exception, webhook enqueue fault)
When the bridge handler catches the exception
Then a "bridge dispatch failed" error is logged with the exception info
And the handler returns silently
And the event bus continues with its next subscriber (the bridge does not break the bus)
```

#### UC-EB6: Subscription set is fixed

```gherkin
Given the bridge is registered at integration service startup
Then the bridge subscribes to these event types only:
  session-started, session-closed, session-updated, agent-event,
  agent-activity, error
And the system-command event type is mapped in the source-map but the bridge does NOT subscribe to it explicitly
```

#### UC-EB7: Matcher dispatch to internal handler

```gherkin
Given a contract targets an internal handler (e.g., "whatsapp_inbound") and matches the event
When the dispatcher iterates matched contracts
Then it looks up the handler in the handler registry
And awaits the handler with the event
And on handler exception: an "internal handler failed" error is logged with the contract id, handler key, and error, and the loop continues to the next contract
```

#### UC-EB8: Matcher dispatch to external URL

```gherkin
Given a contract targets an external URL with an HMAC secret and matches the event
When the dispatcher iterates matched contracts
Then a webhook outbox entry is recorded for the subscriber endpoint (see outbound-webhook-delivery)
And the dispatcher returns; the delivery worker actually transmits the request later
```

#### UC-EB9: Contract with neither handler nor URL is a defect

```gherkin
Given a contract matched the event but its target has neither a handler nor a URL
When the dispatcher evaluates the contract
Then a warning "contract <id> matched but has no handler or URL" is logged
And no delivery action is taken
```

### Cross-context references

- Producer of hook events that downstream contracts consume — contracts
  themselves are managed via `subscriber-driven-contract-routing`
  (the named-exception snippet for v2 inheritance).
- The bridge emits events with source ∈ `{"system", "agent"}` per the
  source-map, and type patterns `session.*`, `agent.*`,
  `agent.activity.*`, `error.*`. The three v1 built-in production
  contracts do NOT match these:
  - `builtin-whatsapp-inbound` matches source="whatsapp" (driven by
    `whatsapp-inbound-conversation-routing` via the inbound framework)
  - `deployment-github` matches source="github" (driven by
    `github-webhook-normalization` via the inbound framework)
  - `deployment-fanout` matches source="deployment" (driven by
    `deployment-version-fanout` via the cross-host channel consumer)
    These built-ins are wired to dispatcher entry points other than this
    bridge. The bridge's potential consumers are user-published contracts
    declaring source ∈ `{"system", "agent"}` — and v1 production has
    none.
- The webhook enqueue side feeds `outbound-webhook-delivery` whenever a
  matched contract has a URL target. In v1 production this path is
  inactive because no contract matches bridge events.
- Internal handler dispatch reaches `whatsapp-inbound-conversation-routing`
  and the deployment handler ONLY for events arriving from the inbound
  framework or the cross-host fanout consumer — not from this bridge.

## Known caveats

- The bridge subscribes at startup and never resubscribes. Event-bus
  events emitted before the bridge is registered are not delivered.
- The bridge uses cluster-visibility semantics implicitly via the event
  bus's own publish path; the dispatch decision (handler vs URL) is
  purely contract-driven.
- All exceptions inside the bridge handler are swallowed by design — the
  bridge must never crash an event-bus subscriber, because that would
  break unrelated consumers on the same bus.
- The source-map's "agent" mapping for agent events is fixed; adding a
  new event-bus type requires both subscribing on the bus and a new
  entry in this map.
- Internal handler exceptions are caught per-contract; the loop continues
  to the next matching contract. A misbehaving handler cannot block
  delivery to other contracts.
- Webhook enqueue failures are caught and logged but do NOT raise; if
  the outbox store is unavailable, the event is dropped after a log
  entry — there is no in-memory retry queue at the bridge layer.
