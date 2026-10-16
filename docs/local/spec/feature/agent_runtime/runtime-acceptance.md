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

Persistent terminal commands complete only after a whole newline-terminated
status frame is received. The controller consumes that frame and preserves any
following bytes for the next command. Partial numeric status is not a completed
command result.

The curation-refusal journey verifies its fresh fixture's empty memory result
through authorized listings both before and after the attempts, against captured
public-output snapshots rather than rendered line counts. Comparison normalizes
PTY line endings and removes only the controller's added separator newline;
extra content, missing output, errors and transport failures still fail. A failed
journey retains bounded sanitized before/after listing output when those commands
ran, alongside its refusal/failing-command evidence.

### Release checkout journeys

The full profile exercises the release checkout scenarios in
`local/projects/teleclaude/spec/feature/reconciliation/release-checkout`, the
exact-source and replay scenarios in
`local/projects/teleclaude/spec/feature/reconciliation/channel-gated-self-update`,
and retained-source migration in
`local/projects/teleclaude/spec/feature/config/document-migration`.

These journeys use disposable Git histories and installed runtime environments,
real command processes, and the public maintenance module entry points used by
automation. Their synthetic event files are inputs to those entry points; they
do not replace application decisions or establish a caller identity. The
controller owns cleanup and reports which release journeys ran. The existing
cold profile remains limited to startup and safe entry paths.

<!-- planned:release-development-checkouts -->

### Development checkout journeys

The full profile exercises the development checkout scenarios in
`local/projects/teleclaude/spec/feature/reconciliation/development-checkout`,
the checkout association scenario in
`local/projects/teleclaude/spec/feature/config/project-registry`, and the
contract-view scenarios in
`local/projects/teleclaude/spec/feature/context/checkout-context-selection`.

These journeys run the real installer, Git and public CLI entry points against a
disposable release-channel installation, its upstream repository and its sibling
development location. Conflicting and interrupted destinations are fixture
states supplied before the public entry point runs; they replace no application
decision. The controller owns cleanup of both locations and reports which
development checkout journeys ran.

<!-- /planned:release-development-checkouts -->

<!-- planned:installation-activation-inspection -->

### Installation assessment journeys

The full profile exercises the retained-failure scenario in
`local/projects/teleclaude/spec/feature/integration/installation-assessment` and
the incomplete-adoption scenario in
`local/projects/teleclaude/spec/feature/reconciliation/channel-gated-self-update`.
They reuse the release journeys' disposable installation and public maintenance
module entry points, and observe the assessment state through the operator's
service status entry point. An assessment obligation retained in its earlier
stored form is a fixture state supplied before the entry point runs; the journey
observes it carried forward unchanged. No journey starts an agent, so agent
assessment and ownership scenarios stay outside this profile. The controller
reports which installation assessment journeys ran.

<!-- /planned:installation-activation-inspection -->

<!-- planned:issue-128 -->

### Workflow journeys

The full profile exercises the public journeys of
`local/projects/teleclaude/spec/feature/workflow/item-lifecycle`,
`local/projects/teleclaude/spec/feature/workflow/item-acts` and
`local/projects/teleclaude/spec/feature/workflow/work-review-cycle`.
Journey assertions are independently reviewed against those owning contracts
before harness implementation, under
`general/principle/verification-independence`.

For journeys requiring an agent session, the harness may supply an inert
executable at the external agent-CLI process boundary defined by
`sdlc/concept/functional-test-boundary`. TeleClaude creates the session,
assigns its role and binding, admits its native startup and resolves callers
through the real public paths. The executable follows the provider's documented
hook protocol and terminal interaction contract; its commands invoke public
executables as fresh processes inside the platform-created session. It creates
no session record, caller identity, authentication state or application event
directly, and imports no application modules. Application components,
authentication decisions and persistent storage run for real. The disposable
profile inherits no live host credentials or adapters.

A journey proceeds on positive native-startup and public-operation evidence.
A missing startup, hook failure, unexpected refusal, timeout or cleanup failure
fails the journey. The fixture's command and hook outputs are retained as bounded,
secret-free diagnostics. A fixture does not establish that a model follows an
instruction; the reported coverage identifies the platform behavior it actually
exercises.

Legacy-store fixtures are pre-existing input installed before activation in the
disposable environment. They do not manufacture an authenticated caller or stand
in for a successful claim. Workflow outcomes are observed through public reads,
logs and operation results; a controller does not edit an item into the outcome
under assertion. Each report maps executed journeys to their owning contract and
identifies unexecuted journeys and observations the public surfaces cannot
provide. An unexecuted journey remains unverified.

<!-- /planned:issue-128 -->

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

#### UC-RA10: Candidate verification uses the same full profile as CI

```gherkin
Given a release operator has a final immutable candidate
When release runtime acceptance runs
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

#### UC-RA14:

This journey consumes
`local/projects/teleclaude/spec/feature/session_mirrors/session-id-namespaces`
UC-SIN-6 and
`local/projects/teleclaude/spec/feature/session_mirrors/mirror-reconciliation-loop`
UC-MRL-10.

```gherkin
Given an agent runs the full acceptance profile with a synthetic native transcript no session record claims
When the runtime archives it and a fresh CLI process searches for a term in its conversation
Then exactly one result names a TeleClaude conversation identity
And history retrieval by that identity and by the transcript's native identity returns the conversation
And after the transcript file is removed and the runtime restarts, history retrieval still returns the conversation
```

#### UC-RA15:

This journey consumes
`local/projects/teleclaude/spec/feature/memory/memory-curation` UC-MC6.

```gherkin
Given an agent runs the full acceptance profile as the authenticated synthetic owner
And the platform has not established that caller as a procedure agent under its system authority
When the owner invokes memory-curation operations through the public CLI
Then each operation is refused
And a fresh authorized memory listing reports no memory added by those attempts
```

## Known caveats

- These journeys establish their named observable behavior, not exhaustive CLI,
  integration, provider, or platform coverage.
- Hosted runtime acceptance does not replace full operating-system installation
  proof, and it uses no live subscription credentials or external messaging.
- Existing installation proof and target-specific worktree help checks retain
  their own contracts.
