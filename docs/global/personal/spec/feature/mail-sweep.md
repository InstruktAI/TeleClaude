---
description: What a mail sweep does, as cases an observer can watch — the incremental pass, the first pass over a backlog, a run with nothing to learn from, and a run correcting itself from what the person did.
---

# Mail Sweep — Spec

## What it is

A sweep is one pass over a person's mail on their behalf. It reads what it did
last time, reads what the person did since, classifies what has arrived, and
leaves one report.

The cases below are what a sweep is answerable for. They say what an observer
sees, never why — the reasoning is the concept's, the steps are the procedure's,
and the outcomes a message may receive are the disposition contract's.

## Canonical fields

Four cases are written because sweeps have exercised them. Four are named without
scenarios because no sweep has produced one yet, and specifying behaviour never
observed would be inventing it. They are listed so the map is complete, and they
are filled in from the first real occurrence.

Named, not yet specified: a set carrying a fact none of its members carries; a
disposition graduating to action; a message too ambiguous to place; a message a
person wrote.

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
And each group is put to the person as one decision carrying its rule, its size, and examples from it
And no group contains a message a person wrote
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
Then a message the person disposed of confirms the disposition it was given
And a message the person returned to the inbox rejects it
And a reply is taken as the strongest endorsement available
And what is concluded about that sender is updated before new mail is classified
And the report names what changed and what evidence changed it
```

## Known caveats

- **A case is watched, not tested.** These bind an assistant's observable
  behaviour in a person's mailbox; there is no harness, and a sweep either
  exhibits a case or does not.
- **Absence of a scenario is deliberate.** The four named cases carry no
  scenario because none has occurred. A scenario written ahead of the first
  occurrence would describe a guess.

## See Also

- ~/.teleclaude/docs/personal/concept/notification-and-record.md — the reasoning these cases produce outcomes from.
- ~/.teleclaude/docs/personal/spec/mail-dispositions.md — the outcomes a message may receive.
- ~/.teleclaude/docs/personal/procedure/email-triage.md — the steps that carry these out.
