---
id: 'project/spec/feature/integration/eventbus-hook-bridge'
type: 'spec'
domain: 'software-development'
scope: 'project'
visibility: 'public'
applies_to: 'v1'
status: 'actual'
description: 'Subscribes to the daemon''s internal EventBus, normalizes each event into a HookEvent, runs it through the Contract matcher, and dispatches to internal handlers or webhook outbox URLs.'
---

# EventBus Hook Bridge — Spec

## Required reads

- @~/.teleclaude/docs/software-development/principle/domain-driven-design.md
- @~/.teleclaude/docs/software-development/spec/domain-spec.md
- @docs/project/spec/domain/integration.md

## What it is

The bridge that connects the in-process `EventBus` (where domain events
like `session_started`, `agent_event`, `agent_activity`, `error` flow) to
the Contract / matcher dispatch path (which fans out to internal handlers
and external webhook URLs). On daemon startup the bridge subscribes to a
fixed set of EventBus event types; on each fired event it computes a
canonical `source` and `type`, packs identifying properties (`session_id`,
`agent_event_type`, `tool_name`, `severity`, `error_source`, `error_code`)
and a payload (raw agent event data, error message), wraps it as a
`HookEvent`, and calls `HookDispatcher.dispatch(event)`.

The bridge is the OUTBOUND side of the integration boundary: it makes the
daemon's internal domain events available as routable HookEvents that
subscribers (Contracts) can react to via internal handlers or external
HTTPS webhook deliveries.

## Canonical fields

### Use cases

#### UC-EB1: Session lifecycle event becomes a session.\* HookEvent

```gherkin
Given the EventBus emits TeleClaudeEvents.SESSION_STARTED with SessionLifecycleContext(session_id="sess-1")
When EventBusBridge._handle runs
Then it detects context is SessionLifecycleContext
And properties = {session_id: "sess-1"}
And hook_type = "session.started" (derived as "session." + event_type.replace("session_", ""))
And source = "system" (from _SOURCE_MAP)
And HookEvent.now(source, type, properties, payload) is built with timestamp = now
And HookDispatcher.dispatch is invoked
And any Contract matching source="system" / type pattern "session.*" / property session_id="sess-1" receives the event
```

#### UC-EB2: Agent event becomes agent.<event_type> HookEvent

```gherkin
Given EventBus emits AGENT_EVENT with AgentEventContext(session_id="s1", event_type="prompt_submitted", data=<raw>)
When _handle runs
Then properties = {session_id: "s1", agent_event_type: "prompt_submitted"}
And hook_type = "agent.prompt_submitted"
And source = "agent"
And if data.raw exists (e.g., the original hook payload), payload = dict(data.raw)
And dispatch is invoked
```

#### UC-EB3: Tool use activity carries tool_name property

```gherkin
Given EventBus emits AGENT_ACTIVITY with ToolUseActivityEvent(session_id="s1", event_type="tool_use", tool_name="Bash")
When _handle runs
Then properties = {session_id: "s1", agent_event_type: "tool_use", tool_name: "Bash"}
And hook_type = "agent.activity.tool_use"
```

#### UC-EB4: Error context translates to error.<severity> with payload message

```gherkin
Given EventBus emits ERROR with ErrorEventContext(session_id="s1", severity="error", source="hook_receiver", code="HOOK_INVALID_JSON", message="bad json")
When _handle runs
Then properties = {session_id: "s1", severity: "error", error_source: "hook_receiver", error_code: "HOOK_INVALID_JSON"}
And hook_type = "error.error"
And payload = {message: "bad json"}
And dispatch is invoked
```

#### UC-EB5: Dispatch failure is logged but does not raise

```gherkin
Given HookDispatcher.dispatch raises (matcher fault, handler exception, webhook enqueue fault)
When _handle catches the exception
Then a logger.error("Bridge dispatch failed: %s", exc) is recorded with exc_info
And _handle returns silently
And the EventBus continues with its next subscriber (the bridge does not break the bus)
```

#### UC-EB6: Subscription set is fixed

```gherkin
Given EventBusBridge.register(event_bus) is called at daemon startup
Then the bridge subscribes to these event types only:
  TeleClaudeEvents.SESSION_STARTED, SESSION_CLOSED, SESSION_UPDATED,
  AGENT_EVENT, AGENT_ACTIVITY, ERROR
And the system_command event type is mapped in _SOURCE_MAP but the bridge does NOT subscribe to it explicitly
```

#### UC-EB7: Matcher dispatch to internal handler

```gherkin
Given a Contract has target=Target(handler="whatsapp_inbound") and matches the event
When HookDispatcher.dispatch runs the for-loop
Then it looks up the handler in HandlerRegistry
And awaits handler(event)
And on handler exception: logger.error("Internal handler failed") with contract_id, handler, error, and the loop continues to next contract
```

#### UC-EB8: Matcher dispatch to external URL

```gherkin
Given a Contract has target=Target(url="https://example.com/webhook", secret="hmac-key") and matches the event
When HookDispatcher.dispatch runs
Then enqueue_webhook(contract_id, event_json, target_url, target_secret) is invoked
And a row is written to webhook_outbox (see outbound-webhook-delivery)
And the dispatcher returns; the delivery worker actually transmits the request later
```

#### UC-EB9: Contract with neither handler nor URL is a defect

```gherkin
Given a Contract matched the event but its target has handler=None and url=None
When HookDispatcher.dispatch evaluates the contract
Then a warning "Contract <id> matched but has no handler or URL" is logged
And no delivery action is taken
```

### Implementation pointers (v1)

- `teleclaude/hooks/bridge.py` — `EventBusBridge` (L40):
  `register`, `attach` (compatibility alias), `_handle`, `_SOURCE_MAP`
  (L28, the agent*event → "agent" / session*\* → "system" mapping).
- `teleclaude/hooks/dispatcher.py` — `HookDispatcher` (L22): `dispatch`,
  `deliver` (compatibility alias). `dispatch` catches per-Contract
  handler exceptions and webhook-enqueue exceptions internally.
- `teleclaude/hooks/handlers.py` — `HandlerRegistry`, `InternalHandler`
  type alias.
- `teleclaude/hooks/registry.py` — `ContractRegistry.match` (filters
  active, non-expired contracts against the event).
- `teleclaude/hooks/matcher.py` —
  `match_event` (L46),
  `match_criterion` (L14),
  `_matches_exact_value` (L36, pattern, exact, and required-presence
  semantics).
- `teleclaude/daemon_event_platform.py` — `bridge.register(event_bus)`
  inside `_init_webhook_service` (~L564, after contract registry is
  populated).
- `teleclaude/core/event_bus.py` — `EventBus.subscribe`.
- `teleclaude/core/events.py` — event types, contexts,
  `TeleClaudeEvents`, `AgentEventContext`, `BaseAgentActivityEvent`,
  `ToolUseActivityEvent`, `ErrorEventContext`,
  `SessionLifecycleContext`.

### Cross-context references

- Producer of HookEvents that downstream Contracts consume — Contracts
  themselves are managed via `subscriber-driven-contract-routing`
  (the named-exception snippet for v2 inheritance).
- The bridge emits events with `source` ∈ `{"system", "agent"}` per
  `_SOURCE_MAP`, and `type` patterns of `session.*`, `agent.*`,
  `agent.activity.*`, `error.*`. The three v1 built-in production
  Contracts do NOT match these:
  - `builtin-whatsapp-inbound` matches `source="whatsapp"` (driven by
    `whatsapp-inbound-conversation-routing` via the inbound framework)
  - `deployment-github` matches `source="github"` (driven by
    `github-webhook-normalization` via the inbound framework)
  - `deployment-fanout` matches `source="deployment"` (driven by
    `deployment-version-fanout` via the Redis stream consumer)
    These built-ins are wired to dispatcher entry points other than this
    bridge. The bridge's potential consumers are user-published Contracts
    declaring `source` ∈ `{"system", "agent"}` — and v1 production has none.
- The webhook enqueue side feeds `outbound-webhook-delivery` whenever a
  matched Contract has a URL target. In v1 production this path is
  inactive because no Contract matches bridge events.
- Internal handler dispatch reaches `whatsapp-inbound-conversation-routing`
  and the deployment handler ONLY for events arriving from the inbound
  framework or the Redis fanout consumer — not from this bridge.

## Known caveats

- The bridge subscribes at startup and never resubscribes. EventBus
  events emitted before the bridge is registered are not delivered.
- The bridge uses `EventVisibility` semantics implicitly via the
  EventBus's own publish path; the dispatch decision (handler vs URL)
  is purely Contract-driven.
- All exceptions inside `_handle` are swallowed by design — the
  bridge must never crash an event-bus subscriber, because that would
  break unrelated consumers on the same bus.
- The `_SOURCE_MAP` mapping `agent_event` → `"agent"` is hard-coded;
  adding a new EventBus type requires both `bus.subscribe` and a new
  entry in this map.
- Internal handler exceptions are caught per-Contract; the loop
  continues to the next matching contract. A misbehaving handler
  cannot block delivery to other contracts.
- Webhook enqueue failures are caught and logged but do NOT raise; if
  the SQLite outbox is unavailable, the event is dropped after a log
  entry — there is no in-memory retry queue at the bridge layer.
