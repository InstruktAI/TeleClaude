---
description: Machine deployment configuration requires a non-empty minor pin for stable enrollment.
---

# Stable Channel Pinning Rule — Spec

## What it is

The machine configuration's deployment block declares the installation's release
channel and, for stable, its minor-series pin. The configuration model rejects
an empty stable pin before a configuration write is accepted. This records the
operator's selected update boundary (`general/policy/human-contract`).

## Canonical fields

`teleclaude/config/_runtime_models.py` owns `DeploymentConfig`, its channel
vocabulary, default and pin validator. `teleclaude/config/_models.py` places
deployment on the machine runtime configuration, and
`teleclaude/config/machine_config_mutation.py` owns the semantic mutation.
Release admission consumes that declaration under
`local/projects/teleclaude/spec/feature/reconciliation/channel-gated-self-update`.

### Use cases

#### UC-CFG-PIN-1: Stable enrollment accepts a non-empty minor pin

```gherkin
Given an operator selects stable enrollment with a non-empty minor pin
When the machine configuration is validated
Then the enrollment is accepted unchanged
```

#### UC-CFG-PIN-2: Stable enrollment requires a non-empty pin

```gherkin
Given an operator selects stable enrollment with an empty pin
When the machine configuration is validated
Then validation reports the missing pin
And the stored configuration is unchanged
```

#### UC-CFG-PIN-3: Alpha enrollment requires no pin

```gherkin
Given an operator selects alpha enrollment without a pin
When the machine configuration is validated
Then the enrollment is accepted
```

#### UC-CFG-PIN-4: Beta enrollment requires no pin

```gherkin
Given an operator selects beta enrollment without a pin
When the machine configuration is validated
Then the enrollment is accepted
```

#### UC-CFG-PIN-5: An absent deployment block uses the model's default

```gherkin
Given an operator has supplied no deployment block
When the machine configuration is loaded
Then enrollment follows the deployment model's default
```

## Known caveats

- The pin validator checks non-emptiness, not a version-series grammar. Release
  selection separately interprets the pin. A non-empty malformed pin is therefore
  not rejected by configuration validation.
