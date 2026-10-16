---
description: Physical closure, independent evidence and final-result ownership for the enclosed runtime acceptance profile.
visibility: internal
delivered_by:
  - issue-128
---

# Runtime Acceptance Finalization — Design

## Purpose

Own the shared flow finalizer's physical proof, observer exclusion, contained
trigger closure and resource-release contract. Execution and acceptance remain
owned by `local/projects/teleclaude/spec/feature/agent_runtime/runtime-acceptance`.
The independent-standard and control-change reasons are
`general/principle/verification-independence` and
`sdlc/policy/process-change-authority`.

## Inputs/Outputs

The frozen shared-finalizer base has SHA-256
`0f854a0cf428947e00f44c992d55442580989d76d367063eec9e8f4e65485fc9`.
That record's bytes remain unchanged. This is its separate, explicitly bound
amendment; it becomes executable authority only with independent review of
this exact amendment and the affected control changes. The base retains its
force wherever this amendment names no replacement.

Inputs are the immutable inner report and effect ledger, per-session public
end/closed evidence (P1), matched accepted-start/claim/operation evidence (P2),
the actual same-generation daemon-stop outcome (P3), and an outside physical
witness (P4). A completed operation with an in-progress start is not a consumed
launch. A closed session record is not physical-exit evidence. Only the actual
`stopped` outcome from the supported make stop path supplies P3. Public reads
and restoration finish before that stop; post-stop public reads supply none.

Outputs retain individual functional outcomes, independent P1–P4 states,
trigger classifications, typed retention causes and owned-resource disposition.
They include the unchanged provisional report, outside witness, recovery prefix
and final aggregate with their byte digests and source/tree/run identities.

## Invariants

### Explicit control amendment

| Base guarantee                                                                                                                                          | Replacement and retained boundary                                                                                                                                                                                                                                        |
| ------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Physical P4 depends on acknowledged launch records, positive exits and public pane closure; unacknowledged launches have no complete proving mechanism. | A closed, continuously bound guest boundary supplies physical P4 for every in-scope process, including unacknowledged launches and long-lived shells. P1/P2 keep their separate public-evidence requirements.                                                            |
| No outside observer exception exists.                                                                                                                   | Only the named outside supervisor, host manager and statically locked provision/query/export helpers are excluded. They run no product/native work outside the guest and follow the sealed one-way admission protocol. Any additional capable creator invalidates proof. |
| A pending implicit trigger has no observed handled/consumed result.                                                                                     | Its semantic state and receipts stay unchanged. A known trigger whose complete creator set is contained may additionally record future execution closed by actual P3 plus accepted P4. This discharges only future creation, never functional delivery or consumption.   |
| Guest finalization produces a final retained failure before an outside witness exists.                                                                  | A newly typed inner stage may defer physical P4. Only the outside owner resolves that typed condition; every genuine failure and unknown remains blocking. Existing failed final reports are never reinterpreted.                                                        |
| All owned home/control/clone/origin resources remain retained because P4 is unavailable.                                                                | A fully evidenced branch may release owned profile resources after durable evidence readback. Failed or unknown branches retain them for the hosted job lifetime; exported diagnostics, not remote rootfs recovery, are the post-job record.                             |

### Physical denominator and closure

The measured denominator is every profile-capable process in the verified guest
subtree from before installation: guest PID 1 and user/system managers, installer
dependencies, daemon, tmux, pane shells, native fixtures, hooks, detached gate
runners, queued starts and all descendants. Placement is global guest
containment, never a payload ancestry or acknowledged-PID census.

P4 requires all of: the original parent continuously active and bound before
guest launch; verified guest poweroff and the same nspawn invocation inactive
without forced termination; sealed host admission, effective instance mask and
no pending activation; accounted helpers unable to reopen admission; unchanged
host boot/manager/run generation and uninterrupted observation; and a valid
recursive `populated 0` read through the original bound observation handle.
The boundary's managed construction is owned by
`local/projects/teleclaude/design/architecture/runtime-acceptance/overview`.

An empty job list, elapsed quiet period, callback/session count, process list,
newly opened same-name cgroup or equal device/inode pair supplies none of the
missing continuity/admission proof. A lost connection, monitoring overflow,
parent movement/deactivation/removal/recreation, dead handle or unknown creator
leaves P4 unproven. Holding a descriptor is not assumed to prevent removal.

Unknown starts/receipts, explicit attach-timeouts, missing lifecycle/claim
evidence, unexplained mutations/effects, malformed ledgers and uncontained or
unknown-origin creators retain independent blocking force. Physical extinction
does not repair any of them. Counts remain diagnostics.

### Ownership, release and restart

The same exclusively owned run retains the sidecar, control pool, plans, clones,
origin, home and rootfs through finalization. Existing public flow restoration,
holds, safe abandon rules, child/session sweeps and their ordering remain in
force. Foreign objects are never swept or released.

Only successful mandatory facts, accepted P4, valid evidence and no remaining
retention cause make resource release eligible. Seal and read back the witness,
provisional report and recovery evidence before release. A release-intent record
precedes bounded removal of ownership-verified resources. Final acceptance
records the actual release outcome and is validated/read back afterwards; a
failed final write or partial release stays failed with recovery evidence.
The exact host instance mask remains an admission tombstone through job end.
The parent may be stopped/collected only after the original-object witness is
sealed; its removal never establishes emptiness. Observer reports/tombstones
have a separate declared lifetime from disposable workload resources.

A new controller or restarted manager cannot resume that run, retry an unknown
start, reuse its identity or adopt a new observation object. It may preserve
available evidence and report unknown closure. A new authorized attempt has a
fresh identity and does not release the old run's retained resources.

## Primary flows

1. Bind run/source/static identities and outside recovery ownership before any
   profile creator; establish the managed boundary and seal admission.
2. Execute public journeys. Classify P1/P2, all starts, triggers and effects;
   perform permitted restoration and public observations while the daemon exists.
3. Obtain actual P3 through the guest's supported make stop path. Preserve
   missing/failed P3 and original assertions separately.
4. Write/fsync the immutable provisional report. Request guest shutdown on either
   payload success or failure through the dedicated guest cleanup unit.
5. Observe closure and original-object P4 outside the guest. Extract only named
   reports from ownership-verified anchored paths; preserve original byte hashes.
6. Resolve only typed deferred P4, preserve all other causes, validate/read back
   evidence, conditionally release resources, and finalize the aggregate. Export
   only authorized named diagnostics under the workflow's own eligibility rules.

## Failure modes

- Failed/missing P1, P2 or P3 remains retained-unproven even with an empty
  diagnostic population. A functional failure retains its own failed verdict.
- Shutdown escalation, reboot, hook failure, timeout or uncertain service outcome
  cannot become normal poweroff proof from a later zero-population observation.
- Missing/corrupt inner reports, invalid seals, extraction symlinks/traversal,
  source/run mismatch, release failure or final readback/export failure prevents
  acceptance. Retain the original error and safe verified evidence prefix;
  another cleanup/export error never replaces it.
- Runner loss or ineligible/failed upload can destroy post-job evidence. No
  cleanup pass or remote resource-recovery promise follows from VM disposal.

## See Also

- docs/local/design/architecture/runtime-acceptance/overview.md
