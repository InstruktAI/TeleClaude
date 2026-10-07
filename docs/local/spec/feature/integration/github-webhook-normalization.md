---
description: 'GitHub webhook payload normalizer producing canonical github.<event> hook events with repo, sender, action, ref properties, plus ping-handshake metadata.'
visibility: 'public'
---

# GitHub Webhook Normalization — Spec

## What it is

The GitHub normalizer is the one translation of a GitHub delivery, shared
by the ingress and every computer's relay delivery. It reads the GitHub
event type from the `X-GitHub-Event` request header (lowercased; defaults
to `unknown`), extracts canonical properties from the payload
(`repository.full_name`, `sender.login`, `action`, `ref`), and produces a
single hook event with `source="github"` and `type=<event>`. For `ping`
events specifically, the normalizer also passes through `zen` and
`hook_id` so downstream handlers can confirm the registration handshake.

<!-- planned-change:event-envelope -->

The normalizer is the GitHub adapter of the ingress. A project receives
GitHub deliveries by declaring a GitHub source in its own configuration
(`local/projects/teleclaude/spec/feature/integration/inbound-webhook-endpoint-framework`).
The ingress reads the event type from a verified delivery and relays it to
the cluster as the platform event `github.<event>`, whose subject is that
project and whose payload is the delivery body. Each computer turns the
relayed event back into the hook event above, stamped with the relayed
event's timestamp, and delivers it to its own hook dispatcher. The
downstream consumer there is the deployment-update handler (matched via a
programmatic contract for events `push` / `release`), which uses the
normalized event to trigger version-fanout logic.

<!-- change:event-envelope -->

The normalizer is the GitHub adapter of the ingress. A project receives
GitHub deliveries by declaring a GitHub source in its own configuration
(`local/projects/teleclaude/spec/feature/integration/inbound-webhook-endpoint-framework`).
The ingress reads the event type from a verified delivery and relays it to
the cluster as the platform event `github.<event>`, whose home is that
project, whose subject is the project's GitHub source, and whose data is the
delivery body. Each computer turns the
relayed event back into the hook event above, stamped with the relayed
event's timestamp, and delivers it to its own hook dispatcher. The
downstream consumer there is the deployment-update handler (matched via a
programmatic contract for events `push` / `release`), which uses the
normalized event to trigger version-fanout logic.

<!-- /planned-change:event-envelope -->

## Canonical fields

### Use cases

#### UC-GH1: Push event normalization

```gherkin
Given a push delivery arrives at the GitHub inbound endpoint with X-GitHub-Event "push"
And a payload containing repository.full_name="InstruktAI/TeleClaude", sender.login="mfaber", ref="refs/heads/main"
When the GitHub normalizer runs
Then it returns a hook event with source="github", type="push", properties={repo: "InstruktAI/TeleClaude", sender: "mfaber", action: None, ref: "refs/heads/main"}, payload=<original payload>
And the hook event timestamp is the relayed event's timestamp in ISO 8601 UTC
```

#### UC-GH2: Release event normalization

```gherkin
Given a release delivery with payload containing action="published" and repository.full_name="InstruktAI/TeleClaude"
And X-GitHub-Event "release"
When the normalizer runs
Then a hook event is returned with source="github", type="release", properties={repo, sender, action: "published", ref: None}, payload=<original>
```

#### UC-GH3: Ping passthrough adds zen + hook_id but has no built-in consumer

```gherkin
Given X-GitHub-Event "ping" with payload containing zen="Mind your words..." and hook_id=12345
When the normalizer runs
Then properties additionally contain zen and hook_id
And the hook event type is "ping"

When the hook event reaches the dispatcher
Then the v1 built-in `deployment-github` contract matches type in {"push", "release"} ONLY
And no built-in production contract matches type "ping"
And the dispatcher returns without delivering the event anywhere
And the ping is effectively dropped — there is no v1 production handler that confirms registration via the dispatched event
And operators see the ping only in inbound delivery logs (accepted); there is no dropped-dispatch trace because the dispatcher returns immediately when the contract registry yields no matches
```

#### UC-GH4: Missing or malformed header → type "unknown"

```gherkin
Given the delivery arrives without an X-GitHub-Event header
When the normalizer runs
Then event_type from the header is the empty string after lowercasing
And the empty fallback is replaced by "unknown"
And the hook event type is "unknown"
```

#### UC-GH5: Header is case-insensitive (X-GitHub-Event vs x-github-event)

```gherkin
Given the ingress lowercases all header names before translation
And the normalizer reads the lowercase spelling
When the header arrives with either capitalization
Then the event type is extracted correctly
```

#### UC-GH6: Malformed repository or sender → null properties

```gherkin
Given the payload has repository as a non-object value (legacy malformed payload)
When the repo-name extractor runs
Then it returns nothing
And properties.repo is null
Similarly for sender.login when sender is not an object
```

#### UC-GH7: Production routing via deployment-github contract

```gherkin
Given the integration service has registered the built-in contract id="deployment-github" with source criterion matching "github", type criterion matching ["push", "release"], and target "deployment_update"
When a normalized GitHub hook event with type="push" reaches the dispatcher
Then the matcher selects the deployment-github contract
And the deployment-event handler is invoked
And the deployment update flow runs (see deployment-version-fanout)
```

#### UC-GH8: A verified delivery is relayed as a GitHub platform event about its project

<!-- planned-change:event-envelope -->

```gherkin
Given the project "web" declares a GitHub source
When GitHub delivers a push signed with that project's secret to /hooks/inbound/github/project/web
Then the cluster receives the platform event "github.push"
And its subject is the project "web"
And its payload is the delivery body
And every computer's hook dispatcher receives the normalized push event once
```

<!-- change:event-envelope -->

```gherkin
Given the project "web" declares a GitHub source
When GitHub delivers a push signed with that project's secret to /hooks/inbound/github/project/web
Then the cluster receives the platform event "github.push"
And its home is the project "web"
And its subject is the project's GitHub source
And its data is the delivery body
And every computer's hook dispatcher receives the normalized push event once
```

<!-- /planned-change:event-envelope -->

### Cross-context references

- The GitHub endpoint is opened by a project's own GitHub source
  declaration, with its secret from that project's `.env`, per
  `inbound-webhook-endpoint-framework`.
- Relay and per-computer delivery are owned by
  `single-ingress-webhook-termination`.
- Downstream deployment-update handler lives in the deployment
  subsystem, a separate component that `integration` calls via the
  contract dispatcher.
- The same normalized event also feeds `deployment-version-fanout` via
  a second contract `deployment-fanout` matching
  source="deployment" / type="version_available" (a different event
  family, produced by the deployment-event handler and re-published on
  the cross-host channel).

## Known caveats

- GitHub events that lack `action` or `ref` produce explicit nulls in
  those property slots (not missing keys) — the matcher's required-
  presence semantics need to accommodate this.
- The normalizer copies the entire payload into the hook event payload;
  downstream handlers can read repository details, commit lists, etc.
  from the payload — properties are a routing summary only.
- The X-GitHub-Event header is the SOURCE OF TRUTH for event type;
  any contradiction between the header and the body shape (e.g., header
  says `push` but body has no `ref`) is preserved as-is in the emitted
  event.
- A GitHub endpoint exists only for a project that declares a GitHub
  source; this repository declares none.
- The `deployment-github` contract matches every relayed GitHub push or
  release, whichever project declared the source. Declaring a GitHub
  source for any project therefore reaches the deployment handler.
- The zen/hook_id ping passthrough is the only event-type-specific
  property branch in this normalizer; every other GitHub event uses the
  same {repo, sender, action, ref} property shape.
