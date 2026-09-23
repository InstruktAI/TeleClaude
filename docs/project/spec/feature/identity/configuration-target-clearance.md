---
description: Configuration mutations are cleared against the verified principal, target instance, affected fields, and agent role.
delivered_by:
  - align-config-cli-ownership
---

# Configuration Target Clearance — Spec

## What it is

Configuration clearance evaluates the resolved caller against the addressed
configuration kind, instance, and affected fields. The CLI verb alone cannot
grant access to every instance of a kind. An agent acting for a human carries
that human's verified principal; its system role can narrow the operation set
but cannot grant an operation the principal lacks.

A person may change settings in their own person overlay, directly or through
an agent. Person-registry identity fields, including platform role, remain
administrator-maintained. A company roster is changed through that company's
configuration resource by a platform administrator. Machine and global
configuration writes remain administrator operations. Project writes also
respect their repository's ownership and commit boundary; naming a project in
the CLI never grants authority over it.

The clearance decision runs before persistence and receives the same subject
and affected-field set that the config owner mutates. A refusal names the
target and the standing needed to perform the operation. The target's stored
state is unchanged by a refusal.

## Canonical fields

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

### Cross-context references

- The config context identifies the kind, instance, fields, and validated
  candidate. The identity context owns clearance for that target.
- `project/spec/feature/config/kind-addressed-configuration` owns the
  addressed CLI resource and its mutation semantics.
- `project/spec/feature/config/organizational-membership` owns roster
  declaration validity, not caller clearance.

## Known caveats

- This contract applies to configuration resources. Other CLI object families
  retain their own authorization contracts until those owners change them.

## See Also

- docs/project/adr/0099-address-configuration-by-kind.md
