---
visibility: public
description: 'The TeleClaude home is one local-only version-controlled history whose
  retained set fails closed: only durable, home-owned, safe, restorable material enters
  it, activation over an already-populated home is idempotent, material already retained
  in breach of the rule surfaces rather than being silently dropped, and roots owned
  by someone else stay foreign.'
delivered_by:
- person-home-repository
---

# Home Repository — Spec

## Required reads

- @docs/project/spec/domain/reconciliation.md

## What it is

The TeleClaude home directory is a single version-controlled history covering
the durable state of every person and company the installation serves. It has
no remote: the history is rollback, never resilience, and nothing about it
presents local history as protection against loss of the machine.

The home is a mixed tree. Alongside the authored configuration and per-person
material that belongs in a permanent record sit secrets, runtime databases,
caches, generated projections, links into other repositories, and machine state
measured in gigabytes — and the secret material is interleaved with the
material worth keeping rather than separated from it. So the home does not
retain what it has not established as safe.

**The retained set fails closed.** Material enters history only when every one
of these holds: it is intentional and authored; it is owned by the home rather
than by another repository or another owner; it is safe to keep indefinitely in
a record that cannot be edited afterward; it is meaningful to restore; and there
is a reason to version it. Material that has not been established as satisfying
that test does not enter history — and that judgement covers material appearing
in the home after the rule is set, not only material present when it was set.
The direction matters because the home grows: a rule that admits by default
retains each new credential store, cache, and projection until someone
remembers to name it.

Because secrecy is a property of the record rather than of the working tree,
ceasing to retain something does not remove what was already retained. Material
found in history in breach of the rule is therefore surfaced rather than
quietly dropped from future retention.

A root inside the home that belongs to another owner — another repository, or a
project a person owns — is foreign to the home's history. The home neither
retains it nor carries it in a commit taken from an enclosing context.

## Canonical fields

### Use cases

#### UC-HOME-1: Activation over a populated home retains only qualifying material

```
Given a home directory holding authored configuration, per-person material, secrets, runtime databases, generated projections, and links into other repositories
And the home is not yet under version control
When an operator activates the home's history
Then the authored, home-owned, safely retainable material is retained
And the secrets, runtime databases, generated projections, and links into other repositories are not retained
And no material is retained merely because it sits inside an otherwise retained directory
```

#### UC-HOME-2: Repeating activation changes nothing

```
Given the home's history has already been activated
When an operator activates it again
Then the retained set is unchanged
And no remote is introduced
```

#### UC-HOME-3: The home has no remote

```
Given the home is under version control
When an agent or operator inspects where the home's history can be published
Then no remote is configured
And no surface presents the home's history as protection against loss of the machine
```

#### UC-HOME-4: Material appearing later is not retained by default

```
Given the home's history is active with its retained set established
When new material appears in the home that has not been established as safe to retain
Then it does not enter history
```

#### UC-HOME-5: Material already retained in breach of the rule surfaces

```
Given material that the retained-set rule excludes is already present in the home's history
When the home's retained set is evaluated
Then that breach is reported to the operator
And it is not treated as resolved by excluding the material from future retention
```

#### UC-HOME-6: A root owned by someone else stays foreign

```
Given a root inside the home that belongs to another owner
When the home's retained set is evaluated
Then that root's contents are not retained by the home
And a commit taken from a context enclosing that root does not carry them
```

## Known caveats

- Backup and resilience are deliberately absent. Introducing a remote,
  replication, migration, or any recovery claim requires a design that settles
  encryption, exclusion of secrets, multi-device conflict, and who owns
  restoration.

## See Also

- ~/.teleclaude/docs/general/design/configuration-tiers.md — the tier model this contract composes with.
