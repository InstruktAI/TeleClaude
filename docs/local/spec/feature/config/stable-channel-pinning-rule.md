---
description: Stable enrollment names the compatibility series an installation automatically follows, with minor-series selection before 1.0 and major-series selection afterward.
visibility: public
---

# Stable Channel Pinning Rule — Spec

## What it is

The machine's deployment configuration records the installation's channel and,
for stable enrollment, its selected compatibility series. Configuration owns
the declaration and validation; selection of an eligible release belongs to
`local/projects/teleclaude/spec/feature/reconciliation/channel-gated-self-update`.

Explicit enrollment preserves the operator's update boundary
(`general/policy/human-contract`). The declared series is independent of which
computer performs development or owns an upstream contribution.

When the machine configuration omits the deployment declaration, the configured channel defaults to alpha.

## Canonical fields

### Compatibility-series declaration

The deployment model owns the field's spelling and serialized schema. A stable
series names a minor line while the major is zero, and a major line once it is
positive. A positive-major series written with a minor, as a minor pin is
written, names that major's line. Ambiguous, malformed, and missing stable
series fail configuration validation before the configuration is stored. Alpha
and beta need no series.

Configuration migrations translate existing deployment declarations into the
current model (`sdlc/policy/backward-compatibility-hygiene`). A pre-1.0 minor pin
retains its minor boundary. A positive-major minor pin becomes that major's
series: enrollment explicitly admits subsequent compatible minor releases.
The migration result names the effective update boundary; it changes neither
the selected channel nor the running checkout revision. Repeating the migration
preserves the recorded selection.

### Use cases

#### UC-CFG-PIN-1: An operator chooses a stable compatibility series

```gherkin
Scenario Outline: An operator sets the stable update boundary
  Given an operator wants stable enrollment to follow compatibility series <series>
  When they configure that series
  Then the installation accepts the selected update boundary

  Examples:
    | series |
    | 0.8    |
    | 1      |
```

#### UC-CFG-PIN-2: An operator can correct an invalid stable series

```gherkin
Given an operator configures stable enrollment with a missing, malformed or ambiguous series
When configuration is validated
Then the operator receives an actionable diagnostic naming the invalid selection
And the stored deployment configuration is unchanged
```

#### UC-CFG-PIN-3: An operator can choose a prerelease channel without a stable series

```gherkin
Scenario Outline: An operator chooses alpha or beta enrollment
  Given an operator selects the <channel> channel without a compatibility series
  When configuration is validated
  Then the enrollment is accepted

  Examples:
    | channel |
    | alpha   |
    | beta    |
```

#### UC-CFG-PIN-4: Beta enrollment requires no compatibility series

#### UC-CFG-PIN-5: An omitted deployment declaration uses the configured default

#### UC-CFG-PIN-6: Existing pins migrate to the selected compatibility boundary

## Known caveats

- Selecting another series changes release eligibility. Availability and health
  of a release remain separate decisions under the release and installation
  contracts.
