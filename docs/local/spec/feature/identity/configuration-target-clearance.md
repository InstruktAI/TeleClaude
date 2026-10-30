---
description: Configuration operations are cleared against the verified principal,
  target instance, affected fields, and agent role.
---

# Configuration Target Clearance — Spec

## What it is

Configuration clearance evaluates the resolved caller against the addressed
configuration kind, instance, operation, and affected fields. The CLI verb alone
cannot grant access to every instance of a kind. An agent acting for a human
carries that human's verified principal; its system role can narrow the
operation set but cannot grant an operation the principal lacks.

<!-- planned-change:local-operator-identity -->

The decision runs in the process that performs the configuration operation,
before it reads governed configuration or persists a change. That process
resolves the caller through the shared principal-resolution capability
(`local/projects/teleclaude/spec/identity-and-auth` §6), applies the verb's role band, and then
applies this target decision. An unidentified caller holds no role and is
refused before any configuration is read.

<!-- change:local-operator-identity -->

The decision runs in the process that performs the configuration operation,
before it reads governed configuration or persists a change. That process
resolves the caller through the shared principal-resolution capability
(`local/projects/teleclaude/spec/identity-and-auth` §6), applies the verb's role band, and then
applies this target decision. A local caller for which nothing resolves an
identity is the computer's operator, the system principal `system:operator`
(`local/projects/teleclaude/spec/identity-and-auth` §2), and is cleared here with
the operator's standing below. A caller whose session identity document names no
admissible session holds no role and is refused before any configuration is
read.

<!-- /planned-change:local-operator-identity -->

A person may read and change their own person configuration, directly or
through an agent, its person-registry identity fields included. A company, its
roster included, is read and changed through that company's configuration
resource by a caller whose effective role for that company is `admin`
(`local/projects/teleclaude/design/architecture/scoped-roles`); a platform administrator holds
that role for every company. Machine and global configuration writes remain
platform-administrator operations. A project's declaration is changed by a
caller whose effective role for that project is `member` or `admin`, the roles
that may run a session in that project
(`local/projects/teleclaude/spec/feature/agent_runtime/session-lifecycle`). The write
also respects the project repository's ownership and commit boundary; naming a
project in the CLI never grants authority over it.

Clearance decides whether a caller may perform an operation on a subject, never
which parts of it: a caller that may patch a subject may patch every field and
section of it, and every caller that may read a subject reads the same fields.
A guardrail finer than that guards no harm that restoring state cannot repair
(`general/principle/trust-and-guardrails`).

<!-- planned-change:local-operator-identity -->

A caller whose principal is a system principal carries no person
(`local/projects/teleclaude/spec/identity-and-auth` §8). It holds no standing that belongs to a
person or to a platform administrator, whatever its system role permits.

<!-- change:local-operator-identity -->

A caller whose principal is a system principal carries no person
(`local/projects/teleclaude/spec/identity-and-auth` §8). The computer's operator,
`system:operator`, holds platform-administrator standing for every configuration
target — machine and global writes, people and companies — while naming no
person. Every other system principal holds no standing that belongs to a
person or to a platform administrator, whatever its system role permits.

<!-- /planned-change:local-operator-identity -->

Caller resolution and the configuration-target decision do not require a valid
machine configuration. Configuration command execution follows
`local/projects/teleclaude/spec/feature/config/machine-config-cli-surface`;
unavailable-daemon recovery follows
`general/policy/machine-config-mutation-authority`.

The clearance decision receives the same subject and affected-field set that the
config owner mutates. A refusal names the target and the standing needed to
perform the operation. The target's stored state is unchanged by a refusal, and
a refused read returns no configuration.

## Canonical fields

### Standing

| Target               | Operation                                                     | Standing required                                   |
| -------------------- | ------------------------------------------------------------- | --------------------------------------------------- |
| computer, global     | list, get                                                     | none beyond the verb band                           |
| computer, global     | init, patch                                                   | platform administrator                              |
| person, own instance | get, patch                                                    | the person                                          |
| person, any instance | get, patch                                                    | platform administrator                              |
| person               | init; removal; invitation; voice-bot credential binding; list | platform administrator                              |
| person               | patch of organizational memberships                           | refused for every caller — read-only projection     |
| company              | list                                                          | platform administrator                              |
| company              | get, patch                                                    | `admin` effective role for that company             |
| company              | init                                                          | none beyond the verb band                           |
| project              | list, get                                                     | none beyond the verb band                           |
| project              | adopt, anywhere                                               | a registered person                                 |
| project              | create in the caller's own home                               | the person                                          |
| project              | create with `--company`                                       | membership of that company, any role                |
| project              | create with `--path`                                          | platform administrator                              |
| project              | patch                                                         | `member` or `admin` effective role for that project |
| company              | help-desk links                                               | `admin` effective role for that company             |
| project              | help-desk links                                               | `admin` effective role for that project             |

### Use cases

#### UC-CTC1: A person's agent edits all of that person's configuration

#### UC-CTC2: Person ownership does not confer platform-role authority

#### UC-CTC3: An agent cannot edit another person's instance by naming it

#### UC-CTC4: A company roster requires the standing of its target

#### UC-CTC5: An administrator can maintain a company roster

#### UC-CTC6: A person cannot read another person's configuration

<!-- planned-change:local-operator-identity -->

#### UC-CTC7: A system principal holds no person or administrator standing

<!-- change:local-operator-identity -->

#### UC-CTC7: A system principal other than the operator holds no person or administrator standing

<!-- /planned-change:local-operator-identity -->

#### UC-CTC8: Computer configuration stays repairable while it is invalid

### Cross-context references

- The config context identifies the kind, instance, fields, and validated
  candidate. The identity context owns clearance for that target.
- `local/projects/teleclaude/spec/feature/config/kind-addressed-configuration` owns the
  addressed CLI resource and its mutation semantics.
- `local/projects/teleclaude/spec/feature/config/organizational-membership` owns roster
  declaration validity, not caller clearance.
- `local/projects/teleclaude/spec/identity-and-auth` owns caller verification and the verb's role
  band this decision follows.

#### UC-CTC9: A company administrator maintains their own company

#### UC-CTC10: A company's help-desk links need that company's administrator

#### UC-CTC11: Whoever may work in a project changes its declaration

#### UC-CTC12: Machine configuration reads the same for every admitted caller

<!-- planned:local-operator-identity -->

#### UC-CTC13: The computer's operator maintains configuration as a platform administrator

```gherkin
Given an agent another application started, for which no session, terminal login or carried identity resolves
When it changes machine configuration, a person's configuration or a company's configuration
Then each change is cleared with platform-administrator standing
And no person is named as the caller
And a caller whose session identity names no admissible session is refused before any configuration is read
```

<!-- /planned:local-operator-identity -->

## Known caveats

- This contract applies to configuration resources. Other CLI object families
  retain their own authorization contracts until those owners change them.
- Every agent runs as the same operating-system account, which can edit
  configuration files directly. Clearance directs agents through the
  configuration surface; it is not a boundary against that account's own file
  access.

- Installation establishes a machine's first platform administrator from its
  own input while no person is registered, and creates the checkout's
  environment settings file from local defaults when none exists
  (`local/projects/teleclaude/spec/feature/reconciliation/fresh-machine-bootstrap`).
  Neither act is a configuration operation, and neither is cleared here. Once a
  person is registered, every addition passes this clearance, and changing
  environment settings stays a cleared operation.

## See Also

- docs/local/adr/0099-address-configuration-by-kind.md
