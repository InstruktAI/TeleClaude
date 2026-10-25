---
description: Every completed CI run on a project's repository reaches the platform
  as an outcome bound to its revision, and a main revision whose declared required
  checks have all passed is announced as green.
visibility: internal
---

# CI Run Outcomes — Spec

## What it is

A project's CI results reach the platform without anyone watching CI. Each
completed run of any workflow on the project's repository is published as a
platform event about that project, bound to the revision it ran on. The project
declares which of its workflows are its required checks: the checks that decide
whether a revision is admitted. A main revision whose required checks have all
passed is announced as green.

Run completions arrive through the project's existing GitHub source, the single
ingress and the platform event stream
(`local/projects/teleclaude/spec/feature/integration/inbound-webhook-endpoint-framework`,
`local/projects/teleclaude/spec/feature/integration/single-ingress-webhook-termination`).
A fact the delivery does not carry, such as which jobs and steps failed, is read
from GitHub through the in-process GitHub client.

Bugs for failed required checks are filed by
`local/projects/teleclaude/spec/feature/workflow/failed-check-bugs`. Whether and
when an installation activates a green revision is owned by its channel's
activation contract.

**Business value:** a revision's CI verdict becomes a fact the platform holds,
so a red check can reach the bug lane and a green one can admit a revision.
Nobody has to watch GitHub.

## Canonical fields

### Run outcome

For a project that declares its GitHub repository and App, each completed run
on its repository is published once as an outcome of the project, whatever its
workflow or branch. It states:

| Fact           | Meaning                                                     |
| -------------- | ----------------------------------------------------------- |
| workflow       | the workflow that ran                                       |
| required check | whether the project declares that workflow a required check |
| branch         | the branch the run checked                                  |
| revision       | the commit the run checked                                  |
| run            | the run's address on GitHub                                 |
| verdict        | `red`, `green` or `none`                                    |
| conclusion     | GitHub's conclusion for the run                             |
| failures       | for a red run, each job that failed with its failed step    |
| update branch  | whether the run checked a dependency-update pull request    |

The verdict is derived from the conclusion:

| Conclusion                                     | Verdict |
| ---------------------------------------------- | ------- |
| failure, timed out, startup failure            | `red`   |
| success                                        | `green` |
| cancelled, skipped, neutral, any other outcome | `none`  |

A cancelled run is `none` because a newer push cancels the run still checking an
older revision. Its cancellation says nothing about that revision.

### Required checks

- A project names its required checks in its own configuration, by workflow.
- Only required checks decide a revision's green. A workflow that does not check
  the revision to be activated, such as an image build or a scheduled run, is not
  named.
- A project that names no required checks, or declares no `ci` block at all,
  still publishes run outcomes, and announces no revision green.

### Revision green

A main revision is green once every required check has a `green` run for it.
The platform publishes that once per revision. The event names the revision and
the run of each required check that made it green. A revision with a `red` or
missing required check is not green, and nothing is published for it.

### Newest green revision of a followed repository

An installation that follows a repository can ask for that repository's newest
green main revision, whether or not its computer receives the repository's run
completions. The answer applies the rule of Revision green: every required
check, as the repository declares them at that revision, has a `green` run for
it. It is read from the repository's run results on GitHub; when those results
cannot be read, the answer says so and names no revision.

### Once per completion

GitHub retries deliveries, and every computer receives every relayed event. The
outcome of one run completion, and the green announcement of one revision, are
each published once. Re-running a run on GitHub is a new completion.

### Use cases

#### UC-RCO1: An operator's project learns how a CI run went on a revision

```gherkin
Given an operator's project receives its repository's CI run completions
When a workflow run completes on the project's repository
Then the platform holds that run's outcome for the project, naming the workflow, branch, revision, run and verdict
And a failed run's outcome also names each job that failed and the step it failed at
```

#### UC-RCO2: A main revision is announced green only once all its required checks pass

```gherkin
Given an operator's project declares two required checks
When both checks pass on the same main revision
Then the platform announces that revision as green once
But a revision on which either check failed, or has not yet passed, is not announced
```

## Known caveats

- Run completions reach the platform only once the repository's webhook delivers
  workflow runs as well as pushes and releases. That registration is an
  operational prerequisite under `docs/local/procedure/deploy.md`. Runs that
  completed before it are not published.
- A computer that is not running when an outcome is published misses it, as for
  every relayed event. It learns the newer outcomes that follow.
- A project's run completions become outcomes once it declares its repository
  and the App through which the platform reads what a delivery lacks, so every
  outcome carries its failures and commit range. A project that relays run
  completions without declaring both publishes no outcomes, because a failed
  run's jobs and steps cannot be read for it.

## See Also

- docs/local/spec/feature/workflow/failed-check-bugs.md — the bugs filed from red required-check outcomes.
- docs/local/spec/feature/integration/github-webhook-normalization.md — how GitHub deliveries become platform events.
