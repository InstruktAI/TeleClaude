---
description: 'Project deployment channel `stable` requires a non-empty `pinned_minor` value; validation rejects empty pins on the stable channel.'
visibility: 'public'
---

# Stable Channel Pinning Rule — Spec

## Required reads

- @docs/project/spec/domain/config.md

## What it is

The project `deployment` block declares which release channel a project tracks
(`alpha`, `beta`, or `stable`) and, for the `stable` channel, which minor
version line the project is pinned to. v1 enforces a single hard rule on this
pairing: a project on the `stable` channel MUST declare a non-empty
`pinned_minor`. Empty pins are rejected at validation time before the project
config is accepted. The two non-stable channels (`alpha`, `beta`) accept any
`pinned_minor` value including the default empty string. The rule prevents
"floating stable" — a `stable` configuration that silently tracks whatever the
latest stable build happens to be — and forces explicit version intent on the
production channel.

## Canonical fields

### Use cases

#### UC-CFG-PIN-1: Stable channel with explicit pinned_minor accepted

```
Given a project config under load with deployment.channel = "stable"
And deployment.pinned_minor = "1.42"
When the stable-channel pinning rule is validated
Then validation passes and the deployment config is accepted unchanged
And the surrounding project overlay validation continues
```

#### UC-CFG-PIN-2: Stable channel with empty pinned_minor rejected

```
Given a project config under load with deployment.channel = "stable"
And deployment.pinned_minor = "" (the default)
When the stable-channel pinning rule is validated
Then a validation error is raised with the message:
  "pinned_minor is required and must be non-empty when channel=stable"
And the schema layer surfaces the validation failure on the deployment field
And the project config load raises before the project-config writer is reachable
```

#### UC-CFG-PIN-3: Alpha channel ignores pinned_minor

```
Given a project config under load with deployment.channel = "alpha"
And deployment.pinned_minor is empty
When the stable-channel pinning rule is validated
Then validation passes and the deployment config is accepted unchanged
And the project is accepted on the alpha channel with no pin
```

#### UC-CFG-PIN-4: Beta channel ignores pinned_minor

```
Given a project config under load with deployment.channel = "beta"
And deployment.pinned_minor is empty
When the stable-channel pinning rule is validated
Then validation passes and the deployment config is accepted unchanged
And the project is accepted on the beta channel with no pin
```

#### UC-CFG-PIN-5: Channel default is alpha

```
Given a project config under load that omits the entire deployment block
When project overlay validation runs
Then the deployment block falls back to its defaults (alpha + empty pin)
And deployment.channel defaults to "alpha"
And deployment.pinned_minor defaults to ""
And validation passes (alpha + empty pin is valid)
```

### Cross-context references

- The `deployment` block currently lives on the project config. The
  `config` domain spec (`project/spec/domain/config.md`) flags this as a
  misplacement and relocates the deployment block to the runtime
  configuration aggregate. The current contract is "deployment is
  per-project" until that move lands.
- Consumed by the runtime auto-update path (release-channel routing in
  the deployment bounded context). The deployment executor reads
  `deployment.channel` and `deployment.pinned_minor` from the project
  config to decide which release to pull.

## Allowed values

- `channel`: `alpha`, `beta`, `stable`. Default: `alpha`.
- `pinned_minor`: any non-empty string when `channel == "stable"`; any string (including empty) otherwise. Default: `""`.

## Known caveats

- **Misplacement noted by domain spec.** v1 places `deployment` on the project overlay. The v2 `config` domain spec calls this a defect and relocates the block to the runtime configuration aggregate in v2. Until the v2 cutover lands, the project config is the source of truth for release channel.
- **No format validation on `pinned_minor`.** v1 only checks non-emptiness. Any non-empty string (including `"not-a-version"`) passes. Format conformance is the deployment executor's concern, not the config schema's.
- **Validation runs on every load.** The validator fires on every project-config load. A previously valid `teleclaude.yml` edited out-of-band to set `channel: stable` without `pinned_minor` will fail to load the next time the runtime or CLI reads the project config.
- **Default-factory means absent deployment block is accepted.** Projects with no `deployment` key at all fall back to the default deployment block (alpha + empty pin). The rule only fires when `channel` is explicitly set to `stable`.
