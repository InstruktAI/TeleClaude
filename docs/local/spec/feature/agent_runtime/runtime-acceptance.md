---
description: Bounded real-process CLI acceptance evidence gates commits and CI
  validation against independently reviewed public journeys.
visibility: internal
---

# Runtime Acceptance — Spec

## What it is

The repository's quality boundary exposes a small CLI acceptance harness with a
cold-entry profile and a full runtime profile. It establishes whether the named
public journeys work on the checked source, under
`local/projects/teleclaude/policy/test-moratorium` and
`general/principle/verification-independence`. Agent runtime owns execution,
result aggregation and commit eligibility. Each exercised capability retains
its existing semantic owner; the harness consumes those public contracts.

## Canonical fields

### Execution and evidence

Every CLI invocation starts a fresh interpreter through the checked checkout's
public executable. The controller uses process boundaries, never imports the
application, and checks expected outcomes rather than merely process survival.
The full profile uses synthetic identities and an isolated disposable operating
environment, with the real daemon, socket, storage and supported configuration
and authentication paths. It does not inherit live host credentials or adapters.
Terminal authentication uses a real terminal. Runtime isolation belongs to the
harness; agents invoking it do not redirect their own home or platform home.

The fast profile covers cold CLI startup, version/help entry paths, the
installer's safe entry path, and the import of every module of the `teleclaude`
package in one fresh interpreter. It runs once against the materialized
prospective commit tree at the sealed commit gate, separately from routine lint,
for a commit carrying any staged path outside documentation and standalone prose;
a commit carrying only those paths changes nothing the profile exercises and
skips it.
The full profile runs for each push to `main`, on a fresh GitHub-hosted macOS
runner, and on the final immutable release candidate before the existing full
installation proof. The same CI run executes
the repository lint, including documentation and agent-artifact validation, on
its own fresh macOS runner; a failure in either fails the run, and a newer push
to the same branch cancels a run still in progress. Both profiles use one
scenario definition and result format. The full profile includes the
cold-entry scenarios and adds the runtime journeys below.

A result identifies the checked revision or materialized tree, selected profile,
executed scenarios, duration and outcome. Failure evidence contains the failing
command, exit status, bounded stdout/stderr and available runtime diagnostics,
with secrets excluded. Every subprocess and scenario has a finite budget;
budgets are set from measured runs. Unexpected exit, timeout, invalid response,
incorrect result, lost state or cleanup failure fails the profile. Expected
refusals are verified against their public result and absence of side effects.
An unexecuted required scenario is not a pass.

Persistent terminal commands complete only after a whole newline-terminated
status frame is received. The controller consumes that frame and preserves any
following bytes for the next command. Partial numeric status is not a completed
command result.

### Use cases

#### UC-RA1: The checked source starts and loads every module

```gherkin
Given an agent validates a proposed source tree
When the cold-entry profile invokes the public CLI and safe installer entry points
And one fresh interpreter imports every module of the package
Then each invocation starts independently and returns its expected public result
And every module imports without error
And an unexpected failure blocks acceptance of that tree
```

#### UC-RA2: A disposable runtime answers a real CLI request

```gherkin
Given an agent starts the full acceptance profile in a fresh disposable environment
When the runtime becomes ready and a CLI process requests its status
Then the request reaches that runtime and reports its readiness
And readiness has not been inferred solely from the continued existence of a process
```

#### UC-RA3: A registered owner acquires caller identity through the public path

```gherkin
Given an agent runs the owner journey with a synthetic owner in a disposable runtime
When the owner is established and signs in through the supported terminal path
Then a fresh CLI process reports that owner's identity and access
And the harness has not manufactured a caller record or bypassed authentication
```

#### UC-RA4: Configuration changes are observable through a separate CLI process

```gherkin
Given an agent runs the configuration journey with an authenticated synthetic owner
When one CLI process changes a permitted configuration value
Then another CLI process reads back that value and the current revision
And an unrelated seeded value remains unchanged
```

#### UC-RA5: Project registration is visible through the public listing

#### UC-RA6: Job discovery and status return coherent public results

#### UC-RA7: A runtime restart preserves accepted state

```gherkin
Given an agent has completed a configuration write in the disposable runtime
When the runtime is restarted through its supported lifecycle
Then fresh CLI processes observe the accepted configuration
And the restarted runtime answers requests within the readiness budget
```

#### UC-RA8: A caller without administrator standing cannot change machine configuration

#### UC-RA9: Every profile reports errors and cleans up its owned resources

```gherkin
Given an agent runs an acceptance profile that succeeds, fails, times out or is interrupted
When execution ends
Then its owned processes and disposable resources are cleaned up
And its result retains the original outcome and any cleanup failure
And a required scenario that did not run is never reported as passed
```

#### UC-RA10: Candidate verification uses the same full profile as CI

```gherkin
Given a release operator has a final immutable candidate
When release runtime acceptance runs
Then the full journey set executes against that exact candidate
And a failure prevents publication even if an earlier source revision passed
And success leaves the full installation proof required
```

#### UC-RA11: Invalid configuration input is refused without changing state

#### UC-RA12:

#### UC-RA13:

#### UC-RA14:

#### UC-RA15:

## Known caveats

- These journeys establish their named observable behavior, not exhaustive CLI,
  integration, provider, or platform coverage.
- Hosted runtime acceptance does not replace full operating-system installation
  proof, and it uses no live subscription credentials or external messaging.
- Existing installation proof and target-specific worktree help checks retain
  their own contracts.
- The module import check loads every module once, in package order, in one
  interpreter. An import cycle that fails only when a different module of the
  cycle is imported first can still pass.
