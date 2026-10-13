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

#### UC-CFG-PIN-1: Stable enrollment accepts an explicit compatibility series

```gherkin
Scenario Outline: An operator selects a stable compatibility series
  Given an operator configures stable enrollment for <series>
  When configuration is validated
  Then the selected series is accepted unchanged

  Examples:
    | series |
    | 0.8    |
    | 1      |
```

#### UC-CFG-PIN-2: An invalid stable series is refused

```gherkin
Given an operator supplies a missing, malformed or ambiguous stable series
When configuration is validated
Then the operator receives a diagnostic naming the invalid selection
And the stored deployment configuration is unchanged
```

#### UC-CFG-PIN-3: Alpha enrollment requires no compatibility series

```gherkin
Given an operator selects alpha without a compatibility series
When configuration is validated
Then the enrollment is accepted
```

#### UC-CFG-PIN-4: Beta enrollment requires no compatibility series

```gherkin
Given an operator selects beta without a compatibility series
When configuration is validated
Then the enrollment is accepted
```

#### UC-CFG-PIN-5: An omitted deployment declaration uses the configured default

```gherkin
Given an operator has supplied no deployment declaration
When the machine configuration is loaded
Then enrollment follows the deployment model's default
```

#### UC-CFG-PIN-6: Existing pins migrate to the selected compatibility boundary

```gherkin
Scenario Outline: An operator's existing pin is brought forward
  Given an installation has the existing minor pin <pin>
  When its configuration migration completes
  Then the operator can observe the effective compatibility series <series>
  And another migration run preserves that series

  Examples:
    | pin | series |
    | 0.8 | 0.8    |
    | 1.8 | 1      |
```

## Known caveats

- Selecting another series changes release eligibility. Availability and health
  of a release remain separate decisions under the release and installation
  contracts.
