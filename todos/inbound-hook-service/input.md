# Input: inbound-hook-service

## The problem

The hook service has a complete outbound path (internal events → contract match → external delivery) but the inbound path — external platforms sending webhooks INTO TeleClaude — is half-built. The `InboundEndpointRegistry` and `NormalizerRegistry` exist as code but are never instantiated by the daemon. Zero normalizers exist. The subscription-driven model where a user declares interest and the system wires everything is missing.

## What exists (inventory from codebase investigation)

### Built and working

- **Transport layer:** Redis stream channels with consumer groups, publisher, consumer (`teleclaude/channels/`)
- **Subscription worker:** `run_subscription_worker()` in `teleclaude/channels/worker.py` — poll loop, filter matching, dispatch routing. Two target types: `notification` (wired) and `command` (stubbed, logs only)
- **Config schema:** `ChannelSubscription` with `channel`, `filter`, `target` fields. `HooksConfig` with `inbound` and `subscriptions`. `InboundSourceConfig` with `path`, `verify_token`, `secret`, `normalizer`
- **Inbound endpoint framework:** `InboundEndpointRegistry` mounts dynamic FastAPI routes (GET verification + POST payload). HMAC signature verification. Normalizer pipeline
- **Contract system:** Full contract-based matching, DB persistence, in-memory cache, TTL sweep
- **Outbox delivery:** Retry with backoff, dead-lettering for external URL targets

### Built but not wired

- **Subscription worker** is never started by the daemon. `config.project.channel_subscriptions` is never read
- **`InboundEndpointRegistry`** is never instantiated in `_init_webhook_service()`
- **`NormalizerRegistry`** is never instantiated

### Missing entirely

- **Normalizers:** No GitHub normalizer, no WhatsApp normalizer. Empty infrastructure
- **Path derivation:** No deterministic path generation from subscription parameters. Paths are hardcoded in config or fall back to `f"/hooks/{source_name}"`
- **Command dispatch:** Worker's `_dispatch_to_target` for `type: command` is stubbed (logs only)
- **Handler resolution:** No Python module import mechanism for handlers. No `language` setting
- **`telec sync` webhook registration:** Nothing creates webhooks on external platforms
- **Webhook state tracking:** No storage of external webhook IDs for update/delete on subsequent syncs

## Design direction (from brainstorm)

### Core principle: subscriber-driven, convention over configuration

The user declares interest. The system wires everything: endpoint, normalizer, channel, reader, handler mapping. `telec sync` deploys it all. The user writes handler code and a config block. Nothing else.

### Three layers

1. **Transport (invisible).** Redis pubsub channels. Nobody configures them. The system creates and manages them. This is pure plumbing.

2. **Inbound reception.** External platforms POST webhooks to TeleClaude. Endpoint paths are derived deterministically from subscription parameters (project, source type). The path encodes enough to route back without a lookup table. Normalizer transforms platform payload to `HookEvent` if typed. Raw passthrough if untyped. Event publishes onto transport.

3. **Execution.** A reader (the subscription worker) picks up events from transport and maps them to user code. Deployed by `telec sync`. Invokes handlers. Logs success/failure. Retries on failure: immediate → 10s → 30s (3 attempts within a minute).

### Handler resolution — two modes

**Python (first-class):**

```yaml
hooks:
  inbound:
    github:
      secret: ${GITHUB_WEBHOOK_SECRET}
      routes:
        push:
          language: python
          module: myproject.hooks.on_push
```

The system imports the module and calls a known entry point (e.g., `handle(event: HookEvent)`). Direct Python call. No subprocess. This is the primary path for Python projects.

**Executable (universal fallback):**

```yaml
routes:
  push:
    command: ./hooks/on-push
```

Subprocess invocation. Normalized HookEvent JSON piped to stdin. Env vars set (`HOOK_SOURCE`, `HOOK_TYPE`, `HOOK_EVENT_ID`). Working directory = project root. Timeout (configurable, default 30s). Exit 0 = success.

### Built-in handlers as global subscriptions (eat our own dog food)

GitHub and WhatsApp handlers ship with TeleClaude as global subscriptions. They are NOT special-cased. They use the exact same subscription mechanism any user would use. They serve as:

1. Real functionality the project needs
2. Reference implementations / examples for users building their own handlers

Location: something like `teleclaude/hooks/normalizers/github.py`, `teleclaude/hooks/normalizers/whatsapp.py`. Registered in global hooks config so every project inherits them.

### Subscription declaration (minimal config)

Typed (with convention):

```yaml
hooks:
  inbound:
    github:
      secret: ${GITHUB_WEBHOOK_SECRET}
      scope: project
      routes:
        push:
          language: python
          module: myproject.hooks.on_push
        release:
          language: python
          module: myproject.hooks.on_release
        '*':
          command: ./hooks/catch-all
```

When type is `github`, conventions kick in:

- Normalizer: built-in GitHub normalizer (parses `X-GitHub-Event` header, GitHub payload structure)
- Endpoint path: derived deterministically (not user-chosen)
- `telec sync`: calls GitHub API to create/update webhook on the repo

Raw/untyped (no normalizer, no platform registration):

```yaml
hooks:
  inbound:
    my-custom-thing:
      secret: ${MY_SECRET}
      routes:
        '*':
          command: ./hooks/handle-anything
```

User provides the webhook URL to the external system themselves. TeleClaude mounts the endpoint, verifies signature, passes raw JSON through.

### Config layering: system defaults vs user config

Built-in platform handlers (WhatsApp, GitHub) are **system defaults** — defined in `config.py` (base configuration), same pattern we already use for other defaults. The user does NOT declare routes, normalizers, or handler modules for built-in platforms. All of that is baked in.

**What the system provides (config.py base defaults):**

- Normalizer (platform-specific)
- Handler module (e.g., `teleclaude.hooks.handlers.whatsapp`)
- Routes (event type → handler mapping)
- Endpoint path derivation
- Verification flow (WhatsApp challenge-response, GitHub ping)

**What the user provides (teleclaude.yml, project config):**

```yaml
hooks:
  inbound:
    whatsapp:
      secret: ${WHATSAPP_SECRET}
    github:
      secret: ${GITHUB_WEBHOOK_SECRET}
```

That's it. Just credentials. The system merges base defaults + user credentials. The `verify_token` for WhatsApp is transient — written by the handler during the verification handshake, not user-managed.

**Activation rules:**

- GitHub: mandatory for TeleClaude's own project — always on
- WhatsApp: activates when secret is present in config
- User-defined (non-built-in): full declaration shape required (routes, handler, normalizer if needed) — no convention to fall back on

**Override policy:** User projects inherit system defaults. Override is limited to what's exposed — secrets, possibly event type filters. Handler modules and routes for built-in platforms are NOT overridable. This prevents misconfiguration while keeping the extension point clean for user-defined hooks.

### Path derivation

Endpoint paths are deterministic, derived from subscription parameters. Not user-chosen, not random UUIDs. The path encodes project + source type + enough identity to route back. Something like `/hooks/inbound/{project}/{source}`. The exact scheme needs design — must support multiple projects subscribing to the same platform type without collision.

Reverse mapping: when a webhook arrives at a path, the system decodes the path back to the project and subscription. No DB lookup needed for routing — the path IS the routing key.

### `telec sync` webhook registration

For typed sources (GitHub, WhatsApp, etc.):

1. Reads `hooks.inbound` config
2. Derives the endpoint path
3. Calls platform API to create/update webhook:
   - GitHub: uses `gh api repos/{owner}/{repo}/hooks` (inherits `gh auth` credentials transparently)
   - WhatsApp: uses WhatsApp Business API
4. Stores returned webhook ID in subscription state (DB) for update/delete on future syncs
5. On config removal: deletes the webhook from the platform

No new credential management needed for GitHub — `gh` CLI handles auth.

### Scope

- `scope: project` — subscription scoped to this project. Endpoint path includes project identifier. Default.
- `scope: global` — TeleClaude-level subscription. Shared across projects. For org-wide hooks where individual projects subscribe downstream.

### Retry semantics for command/handler execution

Not the same as outbox retry (which is for external URL delivery). This is for local handler execution:

- Attempt 1: immediate
- Attempt 2: 10 seconds later
- Attempt 3: 30 seconds later
- After 3 failures: log as failed, do not retry further

Covers transient glitches (daemon restart, temporary unavailability).

## Research findings

### GitHub API via `gh` CLI

No `gh webhook` command. Use `gh api` for full authenticated REST API access:

```bash
gh api repos/{owner}/{repo}/hooks -X POST \
  -f name=web \
  -f 'config[url]=https://our-host/hooks/inbound/project/github' \
  -f 'config[secret]=our-secret' \
  -f 'config[content_type]=json' \
  -F active=true \
  -f 'events[]=push' -f 'events[]=release'
```

From Python: shell out to `gh api` or use `gh auth token` to get a token and call with httpx. Both viable. `gh` handles credential management transparently.

### Channel subscription worker (existing code)

`teleclaude/channels/worker.py:run_subscription_worker()`:

- Polls subscribed channels via Redis XREADGROUP with consumer groups
- Filter matching: each key/value in filter must match payload (AND logic)
- Dispatch targets: `notification` (wired) and `command` (stubbed)
- 5s poll interval
- Graceful shutdown via event

Not started by daemon. `config.project.channel_subscriptions` never read. Needs wiring in daemon startup.

### Normalizer architecture

`NormalizerRegistry` maps string keys to `Callable[[dict], HookEvent]`. A normalizer takes a raw platform payload dict and returns a canonical `HookEvent`. The normalizer extracts:

- `source`: platform name (e.g., "github")
- `type`: event type (e.g., "push", "pull_request") — for GitHub, from `X-GitHub-Event` header
- `properties`: structured metadata (repo, branch, sender, etc.)
- `payload`: the original payload or relevant subset

## WhatsApp alignment

WhatsApp is a critical consumer of the inbound hook service. Understanding how it fits shapes the design.

### Current state

- **No WhatsApp UI adapter exists.** Telegram and Discord have full duplex adapters (receive + send). WhatsApp has nothing — no adapter, no webhook endpoint, no normalizer.
- **`todos/help-desk-whatsapp/`** exists with minimal requirements and an empty implementation plan. Its inbound path depends entirely on the inbound hook service being complete.

### How WhatsApp differs from GitHub

- **GitHub:** webhook per repo, scoped to event types (push, release, PR). Multiple endpoints, each focused.
- **WhatsApp:** ONE global webhook per app. All messages from all users arrive at one endpoint. It's a message firehose, not scoped events.

### The bridge pattern

The WhatsApp inbound handler — registered as a hook service subscription like any other — acts as a boundary adapter. It receives the webhook event through the hook service, translates it to the same internal message format that Telegram and Discord use, and injects it into the adapter pipeline. From that point on, the system doesn't know or care it's WhatsApp.

Flow:

1. WhatsApp Cloud API POSTs to our endpoint (mounted by hook service)
2. WhatsApp normalizer parses Meta's payload → `HookEvent(source="whatsapp", type="message.received", properties={phone, user_id, ...})`
3. Contract matches → routes to WhatsApp handler
4. Handler translates `HookEvent` → internal adapter message format (same as Telegram)
5. Injected into adapter pipeline → session creation, agent routing, response delivery
6. Response goes back via WhatsApp UI adapter (outbound — separate concern, `help-desk-whatsapp` todo)

### What this means for the inbound hook service

- The handler resolution mechanism must support this bridge pattern. A Python module handler that receives a `HookEvent` and calls into the adapter infrastructure.
- WhatsApp's global handler ships with TeleClaude (like GitHub's). It's a global subscription. Every project gets it.
- The WhatsApp normalizer needs to handle Meta's nested payload structure (messages are buried under `entry[].changes[].value.messages[]`).
- Verification: WhatsApp uses the same `hub.verify_token` challenge that the `InboundEndpointRegistry` already supports in its GET handler.

### Dependency

`help-desk-whatsapp` todo (outbound adapter) is a separate deliverable but its inbound path is blocked on `inbound-hook-service`. They should be sequenced: inbound hook service first, then WhatsApp adapter wires into it.

## Open design questions

1. **Exact path derivation scheme.** `/hooks/inbound/{project}/{source}`? How to handle project names with special characters? URL-safe slugification?

2. **Header access in normalizers.** GitHub sends event type in `X-GitHub-Event` header, not in the body. The normalizer needs access to request headers, not just the JSON body. Current `Normalizer` signature is `Callable[[dict], HookEvent]` — may need `Callable[[dict, dict], HookEvent]` (payload, headers) or a richer input object.

3. **Python module handler lifecycle.** Import once at sync/startup and cache? Or import fresh per invocation? Caching is faster but doesn't pick up code changes without restart.

4. **Multiple repos per GitHub subscription.** One webhook config entry covers one repo? Or can a single entry cover multiple repos in the same org?

5. **Global handler override.** If a global GitHub handler exists and a project also declares one, does the project handler replace or supplement the global one?
