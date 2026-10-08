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

The decision runs in the process that performs the configuration operation,
before it reads governed configuration or persists a change. That process
resolves the caller through the shared principal-resolution capability
(`local/projects/teleclaude/spec/identity-and-auth` §6), applies the verb's role band, and then
applies this target decision. An unidentified caller holds no role and is
refused before any configuration is read.

<!-- planned-change:config-clearance-drops-field-gates -->

A person may read and change settings in their own person overlay, directly or
through an agent. Person-registry identity fields, including platform role,
remain platform-administrator-maintained. A company, its roster included, is
read and changed through that company's configuration resource by a caller whose
effective role for that company is `admin`
(`local/projects/teleclaude/design/architecture/scoped-roles`); a platform administrator holds
that role for every company. Machine and global configuration writes remain
platform-administrator operations. Project writes require the `admin` effective
role for that project and also respect their repository's ownership and commit
boundary; naming a project in the CLI never grants authority over it.
<!-- change:config-clearance-drops-field-gates -->

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
<!-- /planned-change:config-clearance-drops-field-gates -->

A caller whose principal is a system principal carries no person
(`local/projects/teleclaude/spec/identity-and-auth` §8). It holds no standing that belongs to a
person or to a platform administrator, whatever its system role permits.

Computer configuration is the daemon's own startup input and stays repairable
while it is invalid
(`local/projects/teleclaude/spec/feature/config/machine-config-cli-surface` UC-CFG-CLI-7).
Deciding its clearance needs no running daemon, and resolving the caller does
not depend on the machine configuration being valid.

The clearance decision receives the same subject and affected-field set that the
config owner mutates. A refusal names the target and the standing needed to
perform the operation. The target's stored state is unchanged by a refusal, and
a refused read returns no configuration.

## Canonical fields

### Standing

<!-- planned-change:config-clearance-drops-field-gates -->

| Target               | Operation                                                                               | Standing required                               |
| -------------------- | --------------------------------------------------------------------------------------- | ----------------------------------------------- |
| computer, global     | list, get                                                                               | none beyond the verb band                       |
| computer, global     | init, patch                                                                             | platform administrator                          |
| person, own instance | get; patch of settings                                                                  | the person                                      |
| person, any instance | get; patch of settings                                                                  | platform administrator                          |
| person               | patch of identity fields; init; removal; invitation; voice-bot credential binding; list | platform administrator                          |
| person               | patch of organizational memberships                                                     | refused for every caller — read-only projection |
| company              | list                                                                                    | platform administrator                          |
| company              | get, patch                                                                              | `admin` effective role for that company         |
| company              | init                                                                                    | none beyond the verb band                       |
| project              | list, get; init of a registered project                                                 | none beyond the verb band                       |
| project              | adopt, anywhere                                                                         | a registered person                             |
| project              | create in the caller's own home                                                         | the person                                      |
| project              | create with `--company`                                                                 | membership of that company, any role            |
| project              | create with `--path`                                                                    | platform administrator                          |
| project              | patch                                                                                   | `admin` effective role for that project         |
| company              | init with `--help-desk`; help-desk links                                                | `admin` effective role for that company         |
| project              | init of the caller's checkout with `--help-desk`; help-desk links                       | `admin` effective role for that project         |

<!-- change:config-clearance-drops-field-gates -->

| Target               | Operation                                                         | Standing required                                   |
| -------------------- | ----------------------------------------------------------------- | --------------------------------------------------- |
| computer, global     | list, get                                                         | none beyond the verb band                           |
| computer, global     | init, patch                                                       | platform administrator                              |
| person, own instance | get, patch                                                        | the person                                          |
| person, any instance | get, patch                                                        | platform administrator                              |
| person               | init; removal; invitation; voice-bot credential binding; list     | platform administrator                              |
| person               | patch of organizational memberships                               | refused for every caller — read-only projection     |
| company              | list                                                              | platform administrator                              |
| company              | get, patch                                                        | `admin` effective role for that company             |
| company              | init                                                              | none beyond the verb band                           |
| project              | list, get; init of a registered project                           | none beyond the verb band                           |
| project              | adopt, anywhere                                                   | a registered person                                 |
| project              | create in the caller's own home                                   | the person                                          |
| project              | create with `--company`                                           | membership of that company, any role                |
| project              | create with `--path`                                              | platform administrator                              |
| project              | patch                                                             | `member` or `admin` effective role for that project |
| company              | help-desk links                                                   | `admin` effective role for that company             |
| project              | init of the caller's checkout with `--help-desk`; help-desk links | `admin` effective role for that project             |

<!-- /planned-change:config-clearance-drops-field-gates -->

### Use cases

<!-- planned-change:config-clearance-drops-field-gates -->

#### UC-CTC1: A person's agent edits that person's settings

```gherkin
Given a person directs an agent bound to their verified principal
And the agent's system role permits configuration patching
When the agent patches that person's own settings
Then the operation is accepted
And the resulting state belongs to that person
```

<!-- change:config-clearance-drops-field-gates -->

#### UC-CTC1: A person's agent edits all of that person's configuration

```gherkin
Given a person directs an agent bound to their verified principal
And the agent's system role permits configuration patching
When the agent patches that person's own configuration, their registry identity fields included
Then the operation is accepted
And the resulting state belongs to that person
```

<!-- /planned-change:config-clearance-drops-field-gates -->

#### UC-CTC2: Person ownership does not confer platform-role authority

<!-- planned-change:config-clearance-drops-field-gates -->

```gherkin
Given a non-administrator directs an agent bound to their verified principal
When the agent attempts to change the person's platform role or registry identity
Then the change is refused before persistence
And the refusal names the administrator standing required for those fields
```

<!-- change:config-clearance-drops-field-gates -->
<!-- /planned-change:config-clearance-drops-field-gates -->

#### UC-CTC3: An agent cannot edit another person's instance by naming it

```gherkin
Given an agent acts for a person without administrator standing
When the agent addresses another person's configuration instance
Then the change is refused before persistence
And the other person's stored state is unchanged
```

#### UC-CTC4: A company roster requires the standing of its target

```gherkin
Given an agent acts for a person whose effective role for a company is not admin
When the agent patches that company's membership or project assignments
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

#### UC-CTC8: Computer configuration stays repairable while it is invalid

```gherkin
Given the committed machine configuration is invalid
And no daemon is listening
When an agent acting for a platform administrator patches the computer configuration to correct it
Then the caller's clearance is decided without the daemon
And the config owner validates and persists the corrected candidate
When an agent whose principal lacks platform administrator standing submits the same patch
Then the operation is refused and the machine configuration is unchanged
```

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

```gherkin
Given an agent acts for a person holding no platform role and the admin role in one company
When it reads or patches that company's roster with valid relationships
Then clearance accepts the targeted operation
And the same person's read or patch of a different company is refused
And their attempt to list every company is refused
```

<!-- planned-change:config-clearance-drops-field-gates -->

#### UC-CTC10: Opening a home to outsiders requires that home's administrator

```gherkin
Given an agent acts for a person whose effective role for a company is member
When it initializes that company with a help desk, or asks for that company's help-desk links
Then the operation is refused before any configuration is read or written
And the refusal names the company administrator standing it requires
And the same operation for a person holding that company's admin role is accepted
```

<!-- change:config-clearance-drops-field-gates -->

#### UC-CTC10: A company's help-desk links need that company's administrator

```gherkin
Given an agent acts for a person whose effective role for a company is member
When it asks for that company's help-desk links
Then the request is refused before any configuration is read
And the refusal names the company administrator standing it requires
And the same request for a person holding that company's admin role is accepted
```

<!-- /planned-change:config-clearance-drops-field-gates -->

<!-- planned:config-clearance-drops-field-gates -->

#### UC-CTC11: Whoever may work in a project changes its declaration

```gherkin
Given an agent acts for a person whose effective role for a project is member
When it patches that project's declaration, its help-desk declaration included
Then clearance accepts the targeted operation
And the same patch for a person whose effective role for that project is below member is refused before persistence
```

#### UC-CTC12: Machine configuration reads the same for every admitted caller

```gherkin
Given a machine configuration holding fields its schema marks sensitive
When an agent acting for a platform administrator and an agent acting for a person below administrator each read it
Then both receive the same view of every field
```

<!-- /planned:config-clearance-drops-field-gates -->

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
