---
description: Assess a retained installed activation after maintenance, recover bounded operational failures, and record evidence without entering development integration.
delivered_by:
  - installation-activation-inspection
role: installation-inspector
subscriptions:
  - teleclaude.integration.installation.maintenance.*
  - teleclaude.system.daemon.restarted
subscription_home: platform
dispatch:
  agent: [claude, codex, gemini, deepseek]
  thinking_mode: med
---

# Installation Inspection — Procedure

## Required reads

- @~/.teleclaude/docs/general/procedure/event-handling/overview.md

## Goal

An installed activation receives one evidence-backed runtime assessment after
its required maintenance, and incomplete work retains an owner and recovery
reference through restarts.

## Preconditions

- The activation or recovery event names the local installation, and the
  procedure runs with its declared inspection role and capabilities.
- The installation's retained assessment and maintenance records are reachable
  through their owning surfaces.
- The project supplies its installation-assessment and service-control
  contracts; discover them through the project's filtered documentation index.

## Steps

<!-- planned:role-scoped-cli-context -->

When this procedure is your session’s launch assignment, retrieve its focused tool
help with `telec -h --expand-role` before starting the assigned work. When reading
it inline, retain your current session’s tool context. Use `telec <command> -h`
for individual commands.
<!-- /planned:role-scoped-cli-context -->

1. Resolve the installed checkout and the event's current assessment record.
   Read intervening state first. A repeat or superseded event is attention to
   reconcile, never authority to repeat an already completed effect.
2. Take the installation's assessment responsibility through its ownership
   surface. If another session owns it, observe that responsibility and leave
   its recovery work to that owner (`general/principle/trust-and-guardrails`).
3. Inspect every owed maintenance result. Pending or interrupted work retains
   its recovery reference. A terminal failure is investigated and recovered
   through the project's sanctioned maintenance or service operation within
   this assignment. Keep health judgment incomplete until the required work
   succeeds.
4. Establish the running revision and read the activated change. Once
   maintenance is ready, inspect a runtime log window that covers activation
   through completed maintenance and includes observation after readiness.
   Judge the evidence against the changed behavior; successful execution of a
   log command is not the verdict (`general/principle/grounding`).
5. Record the assessment against exactly the observed activation evidence.
   Retain any newer activation as outstanding. For a code defect, attach its
   occurrence and installed revision to the associated development project's
   bug process; the installed checkout remains the assessment subject.
6. Release settled responsibility. While owned work remains externally gated,
   use the platform reminder service to retain the next inspection move
   (`general/policy/reminder`). Startup and periodic recovery attention also
   revisit retained incomplete work. A turn owing no report closes under
   `general/policy/no-output-turn`.

## Outputs

- An assessment tied to an installed revision, maintenance result and evidence
  window, or a retained incomplete assessment with its recovery reference.
- A bounded operational recovery outcome or a defect routed to its development
  owner with occurrence evidence.

## Recovery

- Unavailable source or maintenance evidence leaves the assessment incomplete
  and names the missing evidence.
- An unavailable platform runtime requires the project's external or
  service-level recovery path; the procedure records no successful inspection
  for a process it could not observe.
- Inspection operates on installation records and sanctioned recovery surfaces.
  The development integration entrypoint is a different assignment and is not
  a recovery command for this one.
