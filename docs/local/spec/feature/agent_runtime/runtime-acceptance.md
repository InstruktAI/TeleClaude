---
description: Bounded real-process CLI acceptance evidence gates commits and hosted
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

The fast profile covers cold CLI startup, version/help entry paths and the
installer's safe entry path. It runs once against the materialized prospective
commit tree at the sealed commit gate, separately from routine lint. The full
profile runs on GitHub-hosted Ubuntu for normal CI and on the final immutable
release candidate before the existing full installation proof. Both profiles
use one scenario definition and result format. The full profile includes the
cold-entry scenarios and adds the runtime journeys below.

A result identifies the checked revision or materialized tree, selected profile,
executed scenarios, duration and outcome. Failure evidence contains the failing
command, exit status, bounded stdout/stderr and available runtime diagnostics,
with secrets excluded. Every subprocess and scenario has a finite budget;
budgets are set from measured runs. Unexpected exit, timeout, invalid response,
incorrect result, lost state or cleanup failure fails the profile. Expected
refusals are verified against their public result and absence of side effects.
An unexecuted required scenario is not a pass.

### Use cases

#### UC-RA1: Cold public entry points execute from the checked source

```gherkin
Given an agent validates a proposed source tree
When the cold-entry profile invokes the public CLI and safe installer entry points
Then each invocation starts independently and returns its expected public result
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

```gherkin
Given an agent runs the project journey with a disposable project
When the authenticated owner registers that project through the public interface
Then another CLI process lists that project with its expected identity and location
```

#### UC-RA6: Job discovery and status return coherent public results

```gherkin
Given an agent runs the jobs journey for a project with a known inert job declaration
When separate CLI processes request the project's job list and status
Then the declared job is discoverable and its status is consistent with never having run
And the journey starts no provider or externally effectful job
```

#### UC-RA7: A runtime restart preserves accepted state

```gherkin
Given an agent has completed configuration and project writes in the disposable runtime
When the runtime is restarted through its supported lifecycle
Then fresh CLI processes observe the accepted configuration and registered project
And the restarted runtime answers requests within the readiness budget
```

#### UC-RA8: A caller without administrator standing cannot change machine configuration

This journey consumes the role-and-operation refusal contract in
`local/projects/teleclaude/spec/feature/identity/command-clearance` and the
computer-write authority contract in
`local/projects/teleclaude/spec/feature/identity/configuration-target-clearance`.

```gherkin
Given an agent runs the refusal journey with a registered person lacking platform administrator standing
And that person has authenticated through their own terminal
When the person attempts a machine-configuration patch through the public CLI
Then the command refuses the write and identifies the caller role and requested operation
And an administrator reading the configuration afterwards observes the original values and revision
```

#### UC-RA9: Every profile reports errors and cleans up its owned resources

```gherkin
Given an agent runs an acceptance profile that succeeds, fails, times out or is interrupted
When execution ends
Then its owned processes and disposable resources are cleaned up
And its result retains the original outcome and any cleanup failure
And a required scenario that did not run is never reported as passed
```

#### UC-RA10: Candidate verification uses the same full profile as hosted CI

```gherkin
Given a release operator has a final immutable candidate
When hosted runtime acceptance runs
Then the full journey set executes against that exact candidate
And a failure prevents publication even if an earlier source revision passed
And success leaves the full installation proof required
```

#### UC-RA11: Invalid configuration input is refused without changing state

This journey consumes
`local/projects/teleclaude/spec/feature/config/machine-config-cli-surface`
UC-CFG-CLI-3 and
`local/projects/teleclaude/spec/feature/config/unknown-key-warning`.

```gherkin
Given an agent runs the invalid-input journey as the authenticated synthetic administrator
And the machine configuration is valid
When a public configuration patch submits an undeclared top-level key with the current revision
Then the command exits unsuccessfully and identifies the invalid key
And a fresh authorized read reports the original configuration values and revision
```

#### UC-RA12:

This journey consumes the composed-instruction behavior in
`local/projects/teleclaude/spec/feature/context/doc-snippet-three-phase-retrieval`.

```gherkin
Scenario Outline: The public closure request returns its declared instructions or refuses an incomplete result
  Given an agent runs the full acceptance profile with <procedure>
  When a fresh CLI process requests its complete activation closure
  Then it observes <result>

  Examples:
    | procedure                                              | result                                                        |
    | a disposable non-interruptible subscribed procedure     | authored and common instructions, each rendered once          |
    | a disposable interruptible subscribed procedure         | authored, common, and interruption instructions, each once    |
    | a disposable subscribed procedure missing mandatory instructions | a refusal identifying the unavailable instructions    |
```

#### UC-RA13:

This journey consumes the delivery-declaration validation behavior in
`local/projects/teleclaude/spec/feature/context/snippet-frontmatter-validation`.

```gherkin
Given an agent runs the full acceptance profile with disposable procedure source declarations
When the normal documentation validation and publication path receives invalid delivery declarations
Then publication is refused with a finding identifying each invalid declaration
And none of those declarations becomes an active subscription
```

## Known caveats

- These journeys establish their named observable behavior, not exhaustive CLI,
  integration, provider, or platform coverage.
- Hosted runtime acceptance does not replace full operating-system installation
  proof, and it uses no live subscription credentials or external messaging.
- Existing installation proof and target-specific worktree help checks retain
  their own contracts.
