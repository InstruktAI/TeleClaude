---
id: project/spec/feature/integration/github-webhook-normalization
type: spec
domain: software-development
scope: project
visibility: public
applies_to: v1
status: actual
description: GitHub webhook payload normalizer producing canonical github.<event> HookEvents with repo, sender, action, ref properties, plus ping-handshake metadata.
---

# GitHub Webhook Normalization — Spec

## Required reads

- @~/.teleclaude/docs/software-development/principle/domain-driven-design.md
- @~/.teleclaude/docs/software-development/spec/domain-spec.md
- @docs/project/spec/domain/integration.md

## What it is

A normalizer (`normalize_github`) registered against the key `github` in the
NormalizerRegistry. It reads the GitHub event type from the
`X-GitHub-Event` request header (lowercased; defaults to `unknown`),
extracts canonical properties from the JSON payload (`repository.full_name`,
`sender.login`, `action`, `ref`), and produces a single HookEvent with
`source="github"` and `type=<event>`. For `ping` events specifically, the
normalizer also passes through `zen` and `hook_id` so downstream
handlers can confirm the registration handshake.

In v1 production the normalizer is registered at daemon startup as a
built-in. The downstream consumer is the `deployment_update` handler
(matched via a programmatic Contract for events `push` / `release`),
which uses the normalized event to trigger version-fanout logic.

## Canonical fields

### Use cases

#### UC-GH1: Push event normalization

```gherkin
Given a POST /hooks/github arrives with header X-GitHub-Event: push
And JSON body containing repository.full_name="InstruktAI/TeleClaude", sender.login="mfaber", ref="refs/heads/main"
When normalize_github(payload, headers) runs
Then it returns HookEvent(source="github", type="push", properties={repo: "InstruktAI/TeleClaude", sender: "mfaber", action: None, ref: "refs/heads/main"}, payload=<original payload>)
And the HookEvent.timestamp is now() in ISO 8601 UTC
```

#### UC-GH2: Release event normalization

```gherkin
Given a release event with body containing action="published" and repository.full_name="InstruktAI/TeleClaude"
And X-GitHub-Event header is "release"
When normalize_github runs
Then HookEvent(source="github", type="release", properties={repo, sender, action: "published", ref: None}, payload=<original>)
```

#### UC-GH3: Ping passthrough adds zen + hook_id but has no built-in consumer

```gherkin
Given X-GitHub-Event: ping with body containing zen="Mind your words..." and hook_id=12345
When normalize_github runs
Then properties additionally contain zen and hook_id
And the HookEvent type is "ping"

When the HookEvent reaches HookDispatcher.dispatch
Then the v1 built-in `deployment-github` contract matches type in {"push", "release"} ONLY
And no built-in production contract matches type "ping"
And the dispatcher returns without delivering the event anywhere
And the ping is effectively dropped — there is no v1 production handler that confirms registration via the dispatched event
And operators see the ping only in inbound HTTP logs (200 "accepted"); there is no dropped-dispatch trace because `HookDispatcher.dispatch` returns immediately when `ContractRegistry.match` returns an empty list
```

#### UC-GH4: Missing or malformed header → type "unknown"

```gherkin
Given the request arrives without X-GitHub-Event header
When normalize_github runs
Then event_type = (header or "").lower() = ""
And the lowercase fallback "" is replaced by "unknown"
And HookEvent.type = "unknown"
```

#### UC-GH5: Header is case-insensitive (X-GitHub-Event vs x-github-event)

```gherkin
Given the inbound framework lowercases all headers before passing them
And the normalizer reads headers.get("x-github-event") || headers.get("X-GitHub-Event")
When the header arrives with either capitalization
Then both lookups succeed and event_type is extracted correctly
```

#### UC-GH6: Malformed repository or sender → null properties

```gherkin
Given the payload has repository = "not-a-dict" (legacy malformed payload)
When _get_repo_full_name runs
Then it returns None
And properties.repo = None
Similarly for sender.login when sender is not a dict
```

#### UC-GH7: Production routing via deployment-github contract

```gherkin
Given the daemon has registered the built-in contract id="deployment-github" with source_criterion=match "github", type_criterion=match ["push", "release"], target=Target(handler="deployment_update")
When a normalized GitHub HookEvent with type="push" reaches the dispatcher
Then the matcher matches the deployment-github contract
And handle_deployment_event is invoked
And the deployment update flow runs (see deployment-version-fanout)
```

### Implementation pointers (v1)

- `teleclaude/hooks/normalizers/github.py` —
  `normalize_github` (L37),
  `_get_str` (L9),
  `_get_repo_full_name` (L17),
  `_get_sender_login` (L28).
- `teleclaude/hooks/normalizers/__init__.py` —
  `register_builtin_normalizers` (L10) calls
  `registry.register("github", normalize_github)`.
- `teleclaude/daemon_event_platform.py` (inside `_init_webhook_service`
  at L464) — programmatic registration of
  `Contract(id="deployment-github",
  source_criterion=PropertyCriterion(match="github"),
  type_criterion=PropertyCriterion(match=["push", "release"]),
  target=Target(handler="deployment_update"), source="programmatic")`
  (~L496) and `handler_registry.register("deployment_update",
  handle_deployment_event)` (~L495).
- `teleclaude/deployment/handler.py` —
  `configure_deployment_handler` (L34),
  `handle_deployment_event` (L72, the downstream consumer for both
  github- and deployment-source events).
- Verification (HMAC signature) is enforced at the inbound endpoint
  layer (`inbound-webhook-endpoint-framework`), not in the normalizer.

### Cross-context references

- Inbound framework wires the GitHub endpoint when configured at
  `hooks.inbound.github` with `secret: <hmac-key>` per
  `inbound-webhook-endpoint-framework`.
- Downstream `deployment_update` handler lives in
  `teleclaude/deployment/`, a separate subsystem that
  `integration` calls via the Contract dispatcher.
- The same normalized event also feeds `deployment-version-fanout` via
  a second Contract `deployment-fanout` matching
  source="deployment" / type="version_available" (a different event
  family, produced by `handle_deployment_event` and re-published on a
  Redis stream).

## Known caveats

- GitHub events that lack `action` or `ref` produce explicit `None` in
  those property slots (not missing keys) — the matcher's `required`
  semantics need to accommodate this.
- The normalizer copies the entire payload into `HookEvent.payload`;
  downstream handlers can read repository details, commit lists, etc.
  from the payload — properties are a routing summary only.
- The X-GitHub-Event header is the SOURCE OF TRUTH for event type;
  any contradiction between the header and the body shape (e.g.,
  header says `push` but body has no `ref`) is preserved as-is in the
  emitted event.
- In default v1 production, the `/hooks/github` endpoint is registered
  only if `teleclaude.yml.hooks.inbound.github` is present;
  productionconfigs in this repo do not include it. The normalizer
  itself is still registered globally (so a config-driven activation
  is just an additive change).
- The `zen`/`hook_id` ping passthrough is the only event-type-specific
  property branch in this normalizer; every other GitHub event uses
  the same {repo, sender, action, ref} property shape.
