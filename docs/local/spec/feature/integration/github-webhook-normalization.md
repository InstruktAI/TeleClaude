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
events, the normalizer also passes through `zen` and `hook_id` as registration
metadata.

The normalizer is the GitHub adapter of the ingress. A project receives
GitHub deliveries by declaring a GitHub source in its own configuration
(`local/projects/teleclaude/spec/feature/integration/inbound-webhook-endpoint-framework`).
The ingress reads the event type from a verified delivery and relays it to
the cluster as the platform event `github.<event>`, whose origin is that
project, whose subject is the project's GitHub source, and whose data is the
JSON document the delivery carries, in whichever content type GitHub sent it.

Each computer turns the relayed event back into the hook event above, stamped with the relayed
event's timestamp, and delivers it to its own hook dispatcher. A project
that reacts to its own GitHub events deterministically binds their types to
its maintenance actions
(`local/projects/teleclaude/spec/feature/integration/event-bound-maintenance`);
the platform keeps itself current through TeleClaude's own binding of
`github.push` and `github.release`.

## Canonical fields

### Use cases

#### UC-GH1: Push event normalization

#### UC-GH2: Release event normalization

#### UC-GH3: Ping passthrough adds zen + hook_id but has no built-in consumer

#### UC-GH4: Missing or malformed header → type "unknown"

#### UC-GH5: Header is case-insensitive (X-GitHub-Event vs x-github-event)

#### UC-GH6: Malformed repository or sender → null properties

#### UC-GH7: Only the platform's own pushes and releases keep installations current

```gherkin
Given the platform's own repository binds its pushes and releases to the action that keeps an installation current
When a push to the platform's repository is relayed to the cluster
Then every computer holding the platform's checkout performs that action
And a push to any other project's repository does not perform it
```

#### UC-GH8: A verified delivery is relayed as a GitHub platform event about its project

### Cross-context references

- The GitHub endpoint is opened by a project's own GitHub source
  declaration, with its secret from that project's `.env`, per
  `inbound-webhook-endpoint-framework`.
- Relay and per-computer delivery are owned by
  `single-ingress-webhook-termination`.

- Deterministic reactions to GitHub events are a project's own event
  bindings, performed by `event-bound-maintenance`.

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
  source.

- The hook event rebuilt on each computer names the repository, not the
  project that declared the source, so no contract can select GitHub
  events by project.
- A malformed or absent `repository.full_name` or `sender.login` produces an
  explicit null property.
- The zen/hook_id ping passthrough is the only event-type-specific
  property branch in this normalizer; every other GitHub event uses the
  same {repo, sender, action, ref} property shape.
- No built-in contract currently handles a GitHub ping. Its `zen` and
  `hook_id` are normalized, but the unmatched event is not delivered to a
  handler; the inbound delivery is logged as accepted and no dropped-dispatch
  trace is emitted.
