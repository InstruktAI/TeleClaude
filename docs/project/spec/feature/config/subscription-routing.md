---
id: project/spec/feature/config/subscription-routing
type: spec
domain: software-development
scope: project
visibility: public
applies_to: v1
status: actual
description: Subscriptions are a `type`-discriminated union of job-triggered and YouTube subscriptions, each carrying a notification preference that selects the delivery channel (telegram by default).
---

# Subscription Routing — Spec

## Required reads

- @docs/project/spec/domain/config.md

## What it is

A subscription declares interest in a recurring source — either a configured
job (`type: job`) or a YouTube channel (`type: youtube`) — and how the
resulting notifications should be delivered. v1 models this as a discriminated
union: `SubscriptionEntry` is an `Annotated[JobSubscription | YoutubeSubscription, Field(discriminator="type")]`,
which means the `type` field at the YAML level chooses which concrete model
parses the entry. Every subscription carries a `SubscriptionNotification` block
that names the `preferred_channel` (one of `telegram`, `discord`, `whatsapp`,
`email`, defaulting to `telegram`) and an optional `email` override. The same
`SubscriptionEntry` shape is used in two locations: globally, on
`GlobalConfig.subscriptions` (subscriptions that apply across the whole
deployment), and per-person, on `PersonConfig.subscriptions` (subscriptions
that route notifications to a specific principal). The discriminator means
validation routes a single YAML entry to the right concrete model without
ambiguity; an entry with no `type` is rejected by Pydantic before any
content-level validation runs.

## Canonical fields

### Use cases

#### UC-CFG-SUB-1: Job subscription parsed via discriminator

```
Given a subscriptions list entry { type: "job", job: "daily-digest" }
When SubscriptionEntry validation runs
Then the discriminator selects JobSubscription
And JobSubscription.type is the Literal["job"] = "job"
And JobSubscription.job = "daily-digest"
And JobSubscription.when defaults to None
And JobSubscription.enabled defaults to True
And JobSubscription.notification defaults to SubscriptionNotification() (preferred_channel="telegram", email=None)
```

#### UC-CFG-SUB-2: YouTube subscription parsed via discriminator

```
Given a subscriptions list entry { type: "youtube", source: "@channelhandle", tags: ["ai", "research"] }
When SubscriptionEntry validation runs
Then the discriminator selects YoutubeSubscription
And YoutubeSubscription.type is the Literal["youtube"] = "youtube"
And YoutubeSubscription.source = "@channelhandle"
And YoutubeSubscription.tags = ["ai", "research"]
And YoutubeSubscription.enabled defaults to True
And YoutubeSubscription.notification defaults to SubscriptionNotification() (preferred_channel="telegram", email=None)
```

#### UC-CFG-SUB-3: Unknown `type` value rejected by discriminator

```
Given a subscriptions list entry { type: "rss", source: "https://example.com/feed" }
When SubscriptionEntry validation runs
Then Pydantic's discriminator finds no matching member in (JobSubscription, YoutubeSubscription)
And validation fails with a discriminator error naming the invalid tag value
```

#### UC-CFG-SUB-4: Missing `type` field rejected

```
Given a subscriptions list entry { job: "daily-digest" } (no type)
When SubscriptionEntry validation runs
Then Pydantic's discriminator finds no `type` field to dispatch on
And validation fails with a missing-discriminator error before per-model validation
```

#### UC-CFG-SUB-5: Subscription notification defaults to telegram

```
Given any SubscriptionEntry omitting the notification block
When the entry is constructed
Then notification is built via SubscriptionNotification() default-factory
And notification.preferred_channel = "telegram"
And notification.email = None
```

#### UC-CFG-SUB-6: Notification preferred_channel honors enum membership

```
Given a SubscriptionEntry with notification.preferred_channel = "discord"
When SubscriptionNotification validation runs
Then the Literal["telegram", "discord", "whatsapp", "email"] type accepts "discord"
And notification.preferred_channel = "discord"
```

#### UC-CFG-SUB-7: Notification preferred_channel rejects unknown channels

```
Given a SubscriptionEntry with notification.preferred_channel = "sms"
When SubscriptionNotification validation runs
Then the Literal type rejects "sms" (not in telegram|discord|whatsapp|email)
And validation fails with a literal-mismatch error
```

#### UC-CFG-SUB-8: Job subscription may carry its own `when` schedule

```
Given a JobSubscription with when = JobWhenConfig(every="30m")
When JobSubscription validation runs
Then JobWhenConfig validates "30m" per the job-schedule contract
And JobSubscription.when is the validated JobWhenConfig instance
```

#### UC-CFG-SUB-9: Global subscriptions list parses each entry as a discriminated union

```
Given GlobalConfig.subscriptions = [
  { type: "job", job: "daily-digest" },
  { type: "youtube", source: "@channelhandle" }
]
When GlobalConfig validation runs
Then each entry is independently routed through SubscriptionEntry's discriminator
And the resulting list mixes JobSubscription and YoutubeSubscription instances
```

#### UC-CFG-SUB-10: Per-person subscriptions list parses with the same shape

```
Given PersonConfig.subscriptions = [
  { type: "youtube", source: "@channelhandle", tags: ["ai"], notification: { preferred_channel: "discord" } }
]
When PersonConfig validation runs
Then SubscriptionEntry parses the entry as a YoutubeSubscription
And the parsed entry carries notification.preferred_channel = "discord"
```

#### UC-CFG-SUB-11: Subscription enabled flag defaults true and can be set false

```
Given a SubscriptionEntry with enabled = false
When validation runs
Then the inherited Subscription.enabled field accepts the boolean
And enabled = False
And the subscription is registered but suppressed by downstream consumers
```

### Implementation pointers (v1)

- `teleclaude/config/schema.py:201-207` — `SubscriptionNotification` with `preferred_channel` Literal and optional `email`.
- `teleclaude/config/schema.py:209-215` — `Subscription` base model with `enabled` and `notification`.
- `teleclaude/config/schema.py:217-223` — `JobSubscription` with `type: Literal["job"]`, `job` slug, optional `when`.
- `teleclaude/config/schema.py:225-230` — `YoutubeSubscription` with `type: Literal["youtube"]`, `source`, and `tags`.
- `teleclaude/config/schema.py:233-236` — `SubscriptionEntry` Annotated union with `Field(discriminator="type")`.
- `teleclaude/config/schema.py:360` — `GlobalConfig.subscriptions: list[SubscriptionEntry]`.
- `teleclaude/config/schema.py:403` — `PersonConfig.subscriptions: list[SubscriptionEntry]`.

### Cross-context references

- Crosses into the notifications surface via `preferred_channel`. Delivery is owned by the `integration` bounded context: each channel value names a delivery adapter (telegram, discord, whatsapp, email) that lives outside config.
- The `email` override hints at a per-subscription destination that takes precedence over the principal's primary email; the consuming surface (notification dispatcher) decides how to interpret it.
- `JobSubscription.job` references a slug that resolves against `ProjectConfig.jobs` (see `job-schedule-contract.md`). The schema does not enforce reference integrity; an unknown job slug is the dispatcher's problem at runtime, not the config layer's at load time.
- `YoutubeSubscription.source` and `tags` feed the YouTube ingestion pipeline; the schema treats them as opaque strings.

## Allowed values

- `type` (discriminator) — `"job"` or `"youtube"`.
- `notification.preferred_channel` — `"telegram" | "discord" | "whatsapp" | "email"`. Default: `"telegram"`.
- `enabled` — `bool`. Default: `true`.
- `tags` (YouTube only) — list of strings. Default: `[]`.

## Known caveats

- **No referential integrity for `JobSubscription.job`.** The schema accepts any string; whether a job by that slug exists in `ProjectConfig.jobs` is not checked.
- **No format validation on `YoutubeSubscription.source`.** Any string is accepted; the YouTube ingestion adapter decides whether the value resolves.
- **`email` override is opaque to the schema.** `SubscriptionNotification.email` is `str | None` with no format validation (unlike `PersonEntry.email`, which strips and rejects empty).
- **`extra="allow"` on every model.** Unknown YAML keys land on the model silently; typos in field names will not fail validation.
- **Discriminator demands `type` be present.** An entry without a `type` field fails the union dispatch with a discriminator-missing error, not a clearer "type required" message. Surface-level error messages reflect Pydantic's discriminator implementation.
- **Same shape, two homes.** The exact same `SubscriptionEntry` lives on both `GlobalConfig.subscriptions` and `PersonConfig.subscriptions`. The schema does not distinguish global vs. personal semantics; consumers must know which list they are reading and route accordingly.
- **Subscription cardinality and de-duplication are unspecified.** Two identical entries in the same list are both accepted; the dispatcher decides whether to de-duplicate.
