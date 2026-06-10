---
description: 'GitHub webhook payload normalizer producing canonical github.<event> hook events with repo, sender, action, ref properties, plus ping-handshake metadata.'
visibility: 'public'
---

# GitHub Webhook Normalization — Spec

## Required reads

- @~/.teleclaude/docs/software-development/principle/domain-driven-design.md
- @~/.teleclaude/docs/software-development/spec/domain-spec.md
- @docs/project/spec/domain/integration.md

## What it is

A normalizer registered under the key `github` in the normalizer
registry. It reads the GitHub event type from the `X-GitHub-Event`
request header (lowercased; defaults to `unknown`), extracts canonical
properties from the payload (`repository.full_name`, `sender.login`,
`action`, `ref`), and produces a single hook event with `source="github"`
and `type=<event>`. For `ping` events specifically, the normalizer also
passes through `zen` and `hook_id` so downstream handlers can confirm
the registration handshake.

In v1 production the normalizer is registered at integration service
startup as a built-in. The downstream consumer is the deployment-update
handler (matched via a programmatic contract for events `push` /
`release`), which uses the normalized event to trigger version-fanout
logic.

## Canonical fields

### Use cases

#### UC-GH1: Push event normalization

```gherkin
Given a push delivery arrives at the GitHub inbound endpoint with X-GitHub-Event "push"
And a payload containing repository.full_name="InstruktAI/TeleClaude", sender.login="mfaber", ref="refs/heads/main"
When the GitHub normalizer runs
Then it returns a hook event with source="github", type="push", properties={repo: "InstruktAI/TeleClaude", sender: "mfaber", action: None, ref: "refs/heads/main"}, payload=<original payload>
And the hook event timestamp is the current time in ISO 8601 UTC
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
Given the inbound framework lowercases all headers before passing them
And the normalizer reads both the lowercase and titled spellings
When the header arrives with either capitalization
Then both lookups succeed and the event type is extracted correctly
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

### Cross-context references

- Inbound framework wires the GitHub endpoint when configured under
  `hooks.inbound.github` with a `secret` per
  `inbound-webhook-endpoint-framework`.
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
- In default v1 production, the GitHub inbound endpoint is registered
  only when configured under `hooks.inbound.github`; production configs
  in this repo do not include it. The normalizer itself is still
  registered globally (so a config-driven activation is an additive
  change).
- The zen/hook_id ping passthrough is the only event-type-specific
  property branch in this normalizer; every other GitHub event uses the
  same {repo, sender, action, ref} property shape.
