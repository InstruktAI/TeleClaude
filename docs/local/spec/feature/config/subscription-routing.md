---
description: 'Subscriptions are a `type`-discriminated union of job-triggered and YouTube subscriptions, each carrying a notification preference that selects the delivery channel (telegram by default).'
visibility: 'public'
---

# Subscription Routing — Spec

## Required reads

- @docs/local/spec/domain/config.md

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

#### UC-CFG-SUB-1: An owner subscribes to job notifications

```gherkin
Scenario: The owner subscribes a job at a chosen notification destination
  Given a global or person configuration owner wants notifications for a configured job
  When the owner adds an enabled job subscription with a preferred channel
  Then configuration records the job name and chosen notification preference

Scenario: The default destination applies when no preference is supplied
  Given a global or person configuration owner adds a job subscription without a notification preference
  When the configuration loads
  Then the subscription records the default Telegram preference

Scenario: An invalid subscription definition is refused
  Given an owner submits a subscription with a missing or unsupported type, or an unsupported notification channel
  When configuration validates the subscription
  Then the invalid definition is refused with a validation error
  And the subscription is not accepted
```

#### UC-CFG-SUB-2: A person subscribes to a YouTube channel

```gherkin
Given a person wants updates from a YouTube channel with selected tags
When the person adds an enabled YouTube subscription with that channel and tags
Then configuration records that source and tag selection
And it records the selected notification preference or the default Telegram preference
```

#### UC-CFG-SUB-3: Unknown `type` value rejected by discriminator

#### UC-CFG-SUB-4: Missing `type` field rejected

#### UC-CFG-SUB-5: Subscription notification defaults to telegram

#### UC-CFG-SUB-6: Notification preferred_channel honors enum membership

#### UC-CFG-SUB-7: Notification preferred_channel rejects unknown channels

#### UC-CFG-SUB-8: Job subscription may carry its own `when` schedule

#### UC-CFG-SUB-9: Global subscriptions list parses each entry as a discriminated union

#### UC-CFG-SUB-10: Per-person subscriptions list parses with the same shape

#### UC-CFG-SUB-11: An owner pauses or resumes a subscription

```gherkin
Given a subscription has a source and notification preference
When the owner pauses or resumes it
Then configuration changes only its enabled state
And retains the source and notification preference
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
