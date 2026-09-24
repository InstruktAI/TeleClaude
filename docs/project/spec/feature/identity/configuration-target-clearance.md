---
description: Configuration operations are cleared against the verified principal, target instance, affected fields, and agent role.
delivered_by:
  - align-config-cli-ownership
---

# Configuration Target Clearance — Spec

## What it is

Configuration clearance evaluates the resolved caller against the addressed
configuration kind, instance, operation, and affected fields. The CLI verb alone
cannot grant access to every instance of a kind. An agent acting for a human
carries that human's verified principal; its system role can narrow the
operation set but cannot grant an operation the principal lacks.

The decision runs where the caller is verified. The daemon verifies the caller,
applies the verb's role band, and then applies this target decision, before it
reads governed configuration or persists a change
(`project/spec/identity-and-auth` §6). The CLI sends identity signals and
renders the daemon's answer.

A person may read and change settings in their own person overlay, directly or
through an agent. Person-registry identity fields, including platform role,
remain administrator-maintained. A company, its roster included, is read and
changed through that company's configuration resource by a platform
administrator. Machine and global configuration writes remain administrator
operations. Project writes also respect their repository's ownership and commit
boundary; naming a project in the CLI never grants authority over it.

A caller whose principal is a system principal carries no person
(`project/spec/identity-and-auth` §8). It holds no standing that belongs to a
person or to a platform administrator, whatever its system role permits.

Computer configuration is the daemon's own startup input and must stay
repairable while it is invalid
(`project/spec/feature/config/machine-config-cli-surface` UC-CFG-CLI-7). The
computer operation therefore executes in the CLI process after the daemon's
decision. When no daemon is listening, the operation proceeds and records that
no authority was available; a refusal from a running daemon is final.

The clearance decision receives the same subject and affected-field set that the
config owner mutates. A refusal names the target and the standing needed to
perform the operation. The target's stored state is unchanged by a refusal, and
a refused read returns no configuration.

## Canonical fields

### Standing

| Target               | Operation                                                                               | Standing required                               |
| -------------------- | --------------------------------------------------------------------------------------- | ----------------------------------------------- |
| computer, global     | list, get                                                                               | none beyond the verb band                       |
| computer, global     | init, patch                                                                             | platform administrator                          |
| person, own instance | get; patch of settings                                                                  | the person                                      |
| person, any instance | get; patch of settings                                                                  | platform administrator                          |
| person               | patch of identity fields; init; removal; invitation; voice-bot credential binding; list | platform administrator                          |
| person               | patch of organizational memberships                                                     | refused for every caller — read-only projection |
| company              | list, get, patch                                                                        | platform administrator                          |
| company              | init                                                                                    | none beyond the verb band                       |
| project              | list, get; init of the caller's checkout                                                | none beyond the verb band                       |
| project              | patch                                                                                   | platform administrator                          |

### Use cases

#### UC-CTC1: A person's agent edits that person's settings

```gherkin
Given a person directs an agent bound to their verified principal
And the agent's system role permits configuration patching
When the agent patches that person's own settings
Then the operation is accepted
And the resulting state belongs to that person
```

#### UC-CTC2: Person ownership does not confer platform-role authority

```gherkin
Given a non-administrator directs an agent bound to their verified principal
When the agent attempts to change the person's platform role or registry identity
Then the change is refused before persistence
And the refusal names the administrator standing required for those fields
```

#### UC-CTC3: An agent cannot edit another person's instance by naming it

```gherkin
Given an agent acts for a person without administrator standing
When the agent addresses another person's configuration instance
Then the change is refused before persistence
And the other person's stored state is unchanged
```

#### UC-CTC4: A company roster requires the standing of its target

```gherkin
Given an agent acts for a person without platform-administrator standing
When the agent patches a company's membership or project assignments
Then the change is refused before persistence
And neither a permissive system role nor a named company widens the principal's authority
```

#### UC-CTC5: An administrator can maintain a company roster

```gherkin
Given an agent acts for a verified platform administrator
And its system role permits configuration patching
When it patches a registered company's roster with valid relationships
Then clearance accepts the targeted operation
And the config owner validates and persists the requested change
```

#### UC-CTC6: A person cannot read another person's configuration

```gherkin
Given an agent acts for a person without administrator standing
When the agent reads another person's configuration view
Then the read is refused
And no part of that person's configuration is returned
```

#### UC-CTC7: A system principal holds no person or administrator standing

```gherkin
Given an agent session whose principal is a system principal
And its system role permits configuration patching
When it patches a person's settings or a company
Then the change is refused before persistence
And the refusal names the standing the target requires
```

#### UC-CTC8: Computer configuration stays repairable without a running daemon

```gherkin
Given no daemon is listening
And the committed machine configuration is invalid
When an agent patches the computer configuration to correct it
Then the config owner validates and persists the corrected candidate
And the operation records that no authority was available to decide it
When a daemon is running and refuses the same caller
Then the operation stops without a change
```

### Cross-context references

- The config context identifies the kind, instance, fields, and validated
  candidate. The identity context owns clearance for that target.
- `project/spec/feature/config/kind-addressed-configuration` owns the
  addressed CLI resource and its mutation semantics.
- `project/spec/feature/config/organizational-membership` owns roster
  declaration validity, not caller clearance.
- `project/spec/identity-and-auth` owns caller verification and the verb's role
  band this decision follows.

## Known caveats

- This contract applies to configuration resources. Other CLI object families
  retain their own authorization contracts until those owners change them.
- A computer operation performed while no daemon is listening is authorized by
  the operating-system account that runs it, the same account that can start
  the daemon.

## See Also

- docs/project/adr/0099-address-configuration-by-kind.md
