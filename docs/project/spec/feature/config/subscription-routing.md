---
id: 'project/spec/feature/config/subscription-routing'
type: 'spec'
domain: 'software-development'
scope: 'project'
visibility: 'public'
description: 'Subscriptions are a `type`-discriminated union of job-triggered and YouTube subscriptions, each carrying a notification preference that selects the delivery channel (telegram by default).'
---

# Subscription Routing — Spec

## Required reads

- @docs/project/spec/domain/config.md

## What it is

A subscription declares interest in a recurring source — either a configured
job (`type: job`) or a YouTube channel (`type: youtube`) — and how the
resulting notifications should be delivered. v1 models this as a typed union
discriminated by the `type` field: the `type` value at the YAML level selects
which subscription shape parses the entry. Every subscription carries a
notification block that names the `preferred_channel` (one of `telegram`,
`discord`, `whatsapp`, `email`, defaulting to `telegram`) and an optional
`email` override. The same subscription entry shape is used in two locations:
globally, on the global overlay's `subscriptions` (subscriptions that apply
across the whole deployment), and per-person, on the per-person overlay's
`subscriptions` (subscriptions that route notifications to a specific principal).
The discriminator routes a single YAML entry to the right subscription shape
without ambiguity; an entry with no `type` is rejected by the schema before any
content-level validation runs.

## Canonical fields

### Use cases

#### UC-CFG-SUB-1: Job subscription parsed via discriminator

```
Given a subscriptions list entry { type: "job", job: "daily-digest" }
When subscription entry validation runs
Then the discriminator selects a job subscription
And the entry's type field equals "job"
And the entry's job field = "daily-digest"
And the entry's when field defaults to None
And the entry's enabled field defaults to True
And the entry's notification defaults to preferred_channel="telegram", email=None
```

#### UC-CFG-SUB-2: YouTube subscription parsed via discriminator

```
Given a subscriptions list entry { type: "youtube", source: "@channelhandle", tags: ["ai", "research"] }
When subscription entry validation runs
Then the discriminator selects a YouTube subscription
And the entry's type field equals "youtube"
And the entry's source field = "@channelhandle"
And the entry's tags field = ["ai", "research"]
And the entry's enabled field defaults to True
And the entry's notification defaults to preferred_channel="telegram", email=None
```

#### UC-CFG-SUB-3: Unknown `type` value rejected by discriminator

```
Given a subscriptions list entry { type: "rss", source: "https://example.com/feed" }
When subscription entry validation runs
Then the discriminator finds no matching subscription type for "rss"
And validation fails with a discriminator error naming the invalid tag value
```

#### UC-CFG-SUB-4: Missing `type` field rejected

```
Given a subscriptions list entry { job: "daily-digest" } (no type)
When subscription entry validation runs
Then the discriminator finds no `type` field to dispatch on
And validation fails with a missing-discriminator error before per-entry validation
```

#### UC-CFG-SUB-5: Subscription notification defaults to telegram

```
Given any subscription entry omitting the notification block
When the entry is constructed
Then the notification defaults to preferred_channel = "telegram" and email = None
```

#### UC-CFG-SUB-6: Notification preferred_channel honors enum membership

```
Given a subscription entry with notification.preferred_channel = "discord"
When notification validation runs
Then the channel schema accepts "discord" as a valid delivery channel
And notification.preferred_channel = "discord"
```

#### UC-CFG-SUB-7: Notification preferred_channel rejects unknown channels

```
Given a subscription entry with notification.preferred_channel = "sms"
When notification validation runs
Then the channel schema rejects "sms" (not in telegram|discord|whatsapp|email)
And validation fails with a channel-mismatch error
```

#### UC-CFG-SUB-8: Job subscription may carry its own `when` schedule

```
Given a job subscription with a `when` schedule of every="30m"
When job subscription validation runs
Then the `when` schedule is validated per the job-schedule contract
And the subscription's when field holds the validated schedule
```

#### UC-CFG-SUB-9: Global subscriptions list parses each entry as a discriminated union

```
Given the global overlay's subscriptions = [
  { type: "job", job: "daily-digest" },
  { type: "youtube", source: "@channelhandle" }
]
When global overlay validation runs
Then each entry is independently routed through the subscription discriminator
And the resulting list mixes job and YouTube subscription entries
```

#### UC-CFG-SUB-10: Per-person subscriptions list parses with the same shape

```
Given the per-person overlay's subscriptions = [
  { type: "youtube", source: "@channelhandle", tags: ["ai"], notification: { preferred_channel: "discord" } }
]
When per-person overlay validation runs
Then subscription entry validation parses the entry as a YouTube subscription
And the parsed entry carries notification.preferred_channel = "discord"
```

#### UC-CFG-SUB-11: Subscription enabled flag defaults true and can be set false

```
Given a subscription entry with enabled = false
When validation runs
Then the enabled field accepts the boolean
And enabled = False
And the subscription is registered but suppressed by downstream consumers
```

### Cross-context references

- Crosses into the notifications surface via `preferred_channel`.
  Delivery is owned by the `integration` bounded context: each channel
  value names a delivery adapter (telegram, discord, whatsapp, email)
  that lives outside config.
- The `email` override hints at a per-subscription destination that takes
  precedence over the principal's primary email; the notification
  dispatcher decides how to interpret it.
- Job subscriptions reference a job slug that resolves against the
  per-project jobs registry (see `job-schedule-contract.md`). The schema
  does not enforce reference integrity; an unknown job slug is the
  dispatcher's problem at runtime, not the config layer's at load time.
- YouTube subscription `source` and `tags` feed the YouTube ingestion
  pipeline; the schema treats them as opaque strings.

## Allowed values

- `type` (discriminator) — `"job"` or `"youtube"`.
- `notification.preferred_channel` — `"telegram" | "discord" | "whatsapp" | "email"`. Default: `"telegram"`.
- `enabled` — `bool`. Default: `true`.
- `tags` (YouTube only) — list of strings. Default: `[]`.

## Known caveats

- **No referential integrity for the job subscription's `job` slug.** The schema accepts any string; whether a job by that slug exists in the project overlay's jobs mapping is not checked.
- **No format validation on the YouTube subscription's `source`.** Any string is accepted; the YouTube ingestion adapter decides whether the value resolves.
- **`email` override is opaque to the schema.** The notification's `email` field is `str | None` with no format validation (unlike the person entry's `email`, which strips and rejects empty).
- **`extra="allow"` on every model.** Unknown YAML keys land on the model silently; typos in field names will not fail validation.
- **Discriminator demands `type` be present.** An entry without a `type` field fails the union dispatch with a discriminator-missing error, not a clearer "type required" message. Surface-level error messages reflect the schema layer's discriminator implementation.
- **Same shape, two homes.** The exact same subscription entry shape lives on both the global overlay's `subscriptions` and the per-person overlay's `subscriptions`. The schema does not distinguish global vs. personal semantics; consumers must know which list they are reading and route accordingly.
- **Subscription cardinality and de-duplication are unspecified.** Two identical entries in the same list are both accepted; the dispatcher decides whether to de-duplicate.
