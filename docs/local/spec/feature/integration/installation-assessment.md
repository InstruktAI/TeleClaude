---
description: A local installation activation retains its owed assessment through maintenance and restart, and event-activated integrator inspection records the outcome for the exact installed change.
delivered_by:
  - installation-activation-inspection
---

# Installation Assessment — Spec

## What it is

The integrator's installation-inspection assignment judges an installed change
after its mechanical maintenance. Its subject is the installed activation,
independent of whether code arrived from alpha main or an admitted release.
Inspection is an assignment distinct from development-queue delivery, consuming
the procedure's declared role through the shared role-before-launch contract.

Maintenance execution and judgment retain their separate owners
(`local/projects/teleclaude/spec/feature/integration/post-commit-maintenance`).
The event gives attention; the retained activation record supplies the work and
its completion identity (`general/principle/grounding`).

## Canonical fields

### Obligation and readiness

Before activation can restart the daemon, the installation retains its identity,
previous and target revisions, activation time and owed maintenance. Its
inspection obligation survives process restart and ordinary temporary-file
cleanup. It records the maintenance result and assessment separately. A service
manager accepting restart is not a healthy-runtime verdict.

An installation's maintenance reaches a settled result when its required actions
have either succeeded or recorded a terminal failure. The producer publishes
the local installation-maintenance-settled event from that retained result,
carrying its activation reference and outcome. This platform-origin event is
about the installation on its emitting computer; it is not the upstream
repository's release announcement. Event emission can be retried from the
retained obligation after restart without creating new assessment work.

Success makes post-activation log judgment eligible. Failure makes the failed
maintenance available for inspection and bounded recovery while health judgment
remains incomplete. An interrupted action keeps its recovery identity. Startup
and recurring recovery attention reconcile unsettled or unassessed records;
neither an event delivered once nor an agent started once discharges them.

The installation's service status reports an activation whose assessment is
incomplete, with its maintenance result, from the retained record alone, so an
operator observes an unfinished adoption even while the daemon is not
answering.

### Assignment and completion

The subscribed inspection procedure runs against the installed checkout. It
establishes the running revision, reads maintenance outcomes and judges logs
from no later than activation through completed maintenance. Its conclusions
are grounded in the actual changed behavior and runtime evidence, including a
read after readiness. A stale, narrower or earlier log read supplies no
completion for the activation.

One owner holds an installation's current assessment at a time. Delivery
integrator attention and subscribed inspection share that ownership and result;
they do not perform competing recovery. Repeat events reconcile the same
obligation. A successful completion clears only the activation evidence it
actually examined; a newly recorded activation remains outstanding. Every
outcome names its target revision, its evidence window and the start revision
the running daemon reported. A daemon still running from before an activation
that owes its restart cannot supply that completion. A responsibility whose
holder has stopped attending lapses after a bounded interval, so a successor
can take it without a manual release.

The inspection assignment reads, judges and performs bounded operational
recovery through sanctioned maintenance/service surfaces. Code correction is
routed into the registered development checkout and its normal bug lifecycle.
Assessment itself advances no source branch, publishes no mainline commit and
enters no todo-integration queue. The checkpoint and recurring instructions for
this assignment contain its inspection/recovery duties. Mainline publication
remains the delivery assignment's responsibility, consuming the assessment
outcome where that delivery owes one.

### Use cases

#### UC-IAS1: A completed upgrade receives local assessment

```gherkin
Given an operator's installation has activated an admitted release
When its required maintenance succeeds
Then an inspection agent on that installation's computer receives the owed assessment
And the assessment names the activated revision and its maintenance evidence
```

#### UC-IAS2: Assessment does not activate development source

```gherkin
Given an installation inspector assesses a released revision
And its associated development checkout is ahead of that release
When the inspector completes its assignment
Then the installed checkout remains at the admitted release
And the inspection has advanced no development branch or upstream mainline
```

#### UC-IAS3: Restart recovers an interrupted assessment handoff

```gherkin
Given an installation retained an assessment obligation before restart
And delivery of its maintenance attention was interrupted
When the platform resumes and reconciles outstanding installation work
Then an inspection agent can resume that same obligation
And the missing earlier event is not interpreted as completed judgment
```

#### UC-IAS4: A terminal maintenance failure remains actionable

```gherkin
Given an installed activation has a failed required maintenance action
When the inspection agent assesses its recorded result
Then the failed action and its recovery reference remain observable
And the activation is not recorded as healthy merely because the daemon started
```

#### UC-IAS5: Assessment completion cannot erase a newer obligation

```gherkin
Given an inspection agent has observed one installed activation
When a newer activation arrives before it records completion
Then completion of the observed activation leaves the newer one outstanding
```

#### UC-IAS6: Competing attention has one assessment owner

```gherkin
Given delivery and event-driven attention both concern the same installed activation
When agents attempt to take responsibility for its assessment
Then one agent owns that assessment and any recovery it performs
And the other observes the existing responsibility and its eventual result
```

## Known caveats

- A daemon that never becomes available cannot start an agent through its own
  event consumer. Its retained failure needs observation through service-level
  or external operations; successful bootstrap is not fabricated in its absence.
- The procedure's launch role and capability composition are a delivery
  prerequisite, not an exception implemented by the subscription dispatcher.
