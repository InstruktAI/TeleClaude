---
description: A person declares the mail accounts their assistant may act as — each
  naming a normalized connector and an address — separately from the identity address
  by which the person is known.
---

# Person Mail Accounts — Spec

## Required reads

- @docs/local/spec/domain/config.md

## What it is

A person's configuration declares the mail accounts their assistant may act as.
Each entry names the connector the account belongs to and the address itself.
The connector vocabulary is the platform's own — `google` and `microsoft` — so
configuration never names a vendor tool; translating that vocabulary into a
particular tool happens at the boundary that launches it.

The declaration is separate from the person's identity address, which is how a
caller is resolved to a person and is not a mailbox. A person may hold several
accounts across both connectors, or none at all, and neither says anything about
who they are. An identity address becomes an account the assistant may act as
only by being declared as one.

**Business value:** an assistant that knows who it is acting for still has to
know which mailbox it is acting in. Without a declared list there is nothing to
resolve against, so a person holding more than one account leaves the choice to
be guessed. Declaring accounts is what lets the mail boundary refuse rather than
guess, and keeping identity out of that list stops a contact address from
silently becoming a mailbox an agent may act in.

## Canonical fields

### Use cases

#### UC-CFG-MAIL-1: A person with no declared mail accounts is valid

```gherkin
Given an operator configures a person's identity without declaring a mailbox
When the person is resolved
Then they remain resolvable by their identity address
```

#### UC-CFG-MAIL-2: An operator configures a person's mail accounts

```gherkin
Scenario: Declare several supported accounts
  Given an operator declares several mail accounts across the supported connectors
  When the person's configuration is loaded
  Then every account is preserved with its declared connector and address

Scenario: Reject an unsupported connector
  Given an operator declares a mail account using a connector outside the supported vocabulary
  When the person's configuration is loaded
  Then the declaration is rejected with the offending account named
```

#### UC-CFG-MAIL-3: An account naming a connector outside the vocabulary is rejected

#### UC-CFG-MAIL-4: The identity address is not a mail account by itself

```gherkin
Given an operator configures a person's identity address without declaring it as a mail account
When the person is resolved for identity
Then the identity address identifies the person
And it does not grant the assistant a mail account to act as
```

## Known caveats

- An entry declares a connector and an address and nothing further. How a person
  writes, and which of their identities suits a correspondent, is knowledge held
  in the person's own workspace rather than configuration.
- This contract governs what a person may declare. Which declared account an
  invocation acts as, and what it may then do, belongs to the boundary that
  launches the connector.
- Whether the same address may be declared by more than one person is not settled
  by this contract: nothing here validates against it and nothing here entitles
  it. Where it occurs, both declarations resolve to whatever the connector stores
  for that address, including an authorization only one person performed, and
  keeping them apart would need a per-person secret store this contract does not
  own.

## See Also

- docs/local/spec/feature/config/person-identity-schema.md — the identity a person is known by, which this contract deliberately does not treat as a mailbox.
- docs/local/spec/feature/agent_runtime/assistant-connector-access.md — the boundary that consumes these declarations and refuses an invocation not bound to one.
