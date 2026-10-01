---
description: What a mail sweep does, as cases an observer can watch — the incremental pass, the first pass over a backlog, a run with nothing to learn from, and a run correcting itself from what the person did.
---

# Mail Sweep — Spec

## What it is

A sweep is one pass over a person's mail on their behalf. It reads what it did
last time, reads what the person did since, classifies what has arrived, and
leaves one report.

The cases below are what a sweep is answerable for, stated as what an observer
sees.

## Canonical fields

Cases carrying a scenario are binding. Cases named without one are within a
sweep's remit and not yet specified: a set carrying a fact none of its members
carries; a disposition graduating to action; a message too ambiguous to place; a
message a person wrote.

### Use cases

#### UC-SWEEP1: An incremental sweep leaves every considered message with one disposition

```
Given a person whose mail was swept before
When a sweep runs over what has arrived since
Then every message it considered carries exactly one disposition
And no message carries two
And a message needing nothing carries the disposition meaning nothing is proposed
And the run leaves one report naming what it did
```

#### UC-SWEEP2: A first pass over a backlog proceeds by rule and by batch

```
Given a person with a backlog no sweep has touched
When the first pass runs
Then messages are grouped by the rule that would dispose of them
And each unmandated disposal group is put to the person as one decision carrying its rule, its size, and examples from it
And an existing mandate is executed and reported under the conduct policy
And personal correspondence is not disposed of on inference alone
And nothing is disposed of beyond recovery
And the report names each rule applied and how many it covered
```

#### UC-SWEEP3: A run with no human action since the last one continues without inventing a lesson

```
Given a sweep whose previous selection the person has not acted on
When the sweep runs
Then it draws no conclusion from the absence of action
And it classifies what has arrived as it otherwise would
And its report states that the pass was uncorrected
```

#### UC-SWEEP4: A run corrects itself from what the person did to the last selection

```
Given a previous sweep's selection the person has acted on
When the next sweep runs
Then the person's handling is interpreted against the disposition previously proposed
And disposing of a disposal candidate confirms that proposal
And returning disposed mail to the inbox rejects disposal
And a reply establishes the message's relevance
And what is concluded about that sender is updated before new mail is classified
And the report names what changed and what evidence changed it
```

## Known caveats

- **A case is watched, not tested.** These bind an assistant's observable
  behaviour in a person's mailbox; there is no harness, and a sweep either
  exhibits a case or does not.
- **A named case without a scenario binds nothing yet.** It marks remit, and an
  assistant meeting one is not in breach of a contract that has not been written.

## See Also

- ~/.teleclaude/docs/personal/concept/notification-and-record.md — the reasoning these cases produce outcomes from.
- ~/.teleclaude/docs/personal/spec/mail-dispositions.md — the outcomes a message may receive.
- ~/.teleclaude/docs/personal/procedure/email-triage.md — the steps that carry these out.
