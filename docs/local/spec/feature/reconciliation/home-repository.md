---
visibility: public
description: 'The TeleClaude home is one local-only version-controlled history whose
  retained set fails closed: only durable, home-owned, safe, restorable material enters
  it, activation over an already-populated home is idempotent, material already retained
  in breach of the rule surfaces rather than being silently dropped, and roots owned
  by someone else stay foreign.'
---

# Home Repository — Spec

## Required reads

- @docs/local/spec/domain/reconciliation.md

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
project a person owns — is foreign to the home's history and is not part of its
retained set. What a commit boundary does with that answer belongs to the commit
surface that asks it, not to the home's own membership rule.

Activation records only what activation itself writes. Each record holds the
files activation wrote that were unchanged since the last record, or absent,
before it wrote them; when the history is first created there is no last
record, so it holds only files that were absent. Material other authors have
not recorded, whether untracked, modified, or staged, stays exactly as they
left it, and enters history only through its author's own commit. The record is authored under the installation's own identity, never a
person's, and passes the same commit gate as every other commit. An activation
that writes nothing records nothing.

If the commit gate refuses an activation record, activation records nothing,
restores each file it wrote to its previous content or absence, and reports the
gate's findings.

## Canonical fields

### Use cases

#### UC-HOME-1: An operator activates safe local home history

```
Given the home holds configuration and per-person material alongside secrets, runtime databases, generated projections, and foreign repository links
When the operator activates the home's local history
Then only qualifying home-owned material is retained
And secrets, runtime databases, generated projections, and foreign repository links stay excluded
And the history has no remote
```

#### UC-HOME-2: Repeating activation changes nothing

#### UC-HOME-3: The home has no remote

#### UC-HOME-4: Material appearing later is not retained by default

#### UC-HOME-5: An operator finds material already retained outside the rule

```
Given the retained-set rule excludes material already present in the home's history
When the operator evaluates the retained set
Then that breach is reported to the operator
And it is not treated as resolved by excluding the material from future retention
```

#### UC-HOME-6: A root owned by someone else stays foreign

#### UC-HOME-7: Excluded material never enters the record

#### UC-HOME-8: Activation over an active history records only its own writes

#### UC-HOME-9: An activation that writes nothing records nothing

#### UC-HOME-10: The activation's record names the installation as its author

#### UC-HOME-11: A refused activation record leaves the home as activation found it

## Known caveats

- Backup and resilience are deliberately absent. Introducing a remote,
  replication, migration, or any recovery claim requires a design that settles
  encryption, exclusion of secrets, multi-device conflict, and who owns
  restoration.
- The retained set is a statement about paths, not about the bytes of any
  version. A retained path whose content later carries a credential reaches the
  record unexamined; automated per-version secret detection is deliberately not
  part of this contract.

## See Also

- ~/.teleclaude/docs/general/design/configuration-tiers.md — the tier model this contract composes with.
