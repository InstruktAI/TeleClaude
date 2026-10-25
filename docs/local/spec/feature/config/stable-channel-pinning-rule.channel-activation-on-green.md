---
description: The machine configuration declares which channel an installation follows — edge or stable — defaulting to stable, with earlier alpha, beta and omitted declarations migrated to the channel each already followed.
visibility: public
---

# Channel Enrollment — Spec

## What it is

The machine's deployment configuration records the channel the installation
follows. Configuration owns the declaration, its default and its migration;
what each channel admits belongs to
`local/projects/teleclaude/spec/feature/reconciliation/channel-gated-self-update`.
The followed source is the remote of the installation's kept repository
(`local/projects/teleclaude/spec/feature/reconciliation/installed-releases`),
not a configuration field.

The channel is the operator's update boundary (`general/policy/human-contract`):
it is independent of which computer performs development or owns an upstream
contribution, and no compatibility series is declared beside it — the series a
stable installation stays within follows from its active release.

## Canonical fields

### Channel declaration

The deployment model owns the field's spelling and serialized schema. The
channel is `edge` or `stable`; any other value fails configuration validation
before the configuration is stored. A configuration that declares no channel
follows stable, so a new installation whose operator chooses nothing follows
the source's releases.

### Migration of earlier declarations

Configuration migrations translate existing deployment declarations into the
current model (`sdlc/policy/backward-compatibility-hygiene`) without changing
what any installation follows:

| Earlier declaration                | Current declaration |
| ---------------------------------- | ------------------- |
| alpha                              | edge                |
| no channel (which followed main)   | edge                |
| beta                               | stable              |
| stable with a compatibility series | stable              |

A declared compatibility series is dropped. The migration result names the
effective channel; it changes neither the active release nor the source.
Repeating the migration preserves the recorded channel.

### Use cases

#### UC-CFG-PIN-1: An operator chooses a stable compatibility series

#### UC-CFG-PIN-2: An operator can correct an invalid stable series

#### UC-CFG-PIN-3: An operator chooses the channel their installation follows

```gherkin
Scenario Outline: An operator selects a channel
  Given an operator selects the <channel> channel
  When configuration is validated
  Then the enrollment is accepted

  Examples:
    | channel |
    | edge    |
    | stable  |
```

#### UC-CFG-PIN-4: Beta enrollment requires no compatibility series

#### UC-CFG-PIN-5: An omitted deployment declaration uses the configured default

#### UC-CFG-PIN-6: Existing pins migrate to the selected compatibility boundary

## Known caveats

- Selecting another channel changes which revisions are admitted. Availability
  and health of a revision remain separate decisions under the release and
  installation contracts.
