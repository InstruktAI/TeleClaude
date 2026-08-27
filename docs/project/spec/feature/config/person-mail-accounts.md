---
description: 'A person declares the mail accounts their assistant may act as — each naming a normalized connector and an address — separately from the identity address by which the person is known.'
delivered_by:
  - personal-mail-tool-launcher
---

# Person Mail Accounts — Spec

## Required reads

- @docs/project/spec/domain/config.md

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
Given a person whose configuration declares no mail accounts
When that configuration is loaded
Then the person is accepted
And the person is resolvable by their identity address
```

#### UC-CFG-MAIL-2: A person declares several accounts across both connectors

```gherkin
Given a person whose configuration declares more than one mail account
And those accounts name different connectors from the platform's vocabulary
When that configuration is loaded
Then every declared account is preserved with the connector and address it declared
```

#### UC-CFG-MAIL-3: An account naming a connector outside the vocabulary is rejected

```gherkin
Given a person whose configuration declares a mail account naming a connector outside the platform's vocabulary
When that configuration is loaded
Then the configuration is rejected
And the rejection identifies the offending account
```

#### UC-CFG-MAIL-4: The identity address is not a mail account by itself

```gherkin
Given a person whose identity address does not appear among their declared mail accounts
When that configuration is loaded
Then the person's declared accounts do not include their identity address
And the person remains resolvable by that identity address
```

## Known caveats

- An entry declares a connector and an address and nothing further. How a person
  writes, and which of their identities suits a correspondent, is knowledge held
  in the person's own workspace rather than configuration.
- This contract governs what a person may declare. Which declared account an
  invocation acts as, and what it may then do, belongs to the boundary that
  launches the connector.

## See Also

- docs/project/spec/feature/config/person-identity-schema.md — the identity a person is known by, which this contract deliberately does not treat as a mailbox.
- docs/project/spec/feature/agent_runtime/assistant-connector-access.md — the boundary that consumes these declarations and refuses an invocation not bound to one.
