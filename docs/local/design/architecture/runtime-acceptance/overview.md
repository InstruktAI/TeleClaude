---
description: Managed guest enclosure, signed static bindings and finite setup qualification for the one runtime acceptance harness.
visibility: internal
delivered_by:
  - issue-128
---

# Runtime Acceptance Enclosure — Design

## Purpose

Define the static and operational boundary within which the same acceptance
harness executes its payload. The observable execution contract is owned by
`local/projects/teleclaude/spec/feature/agent_runtime/runtime-acceptance`; physical
proof and release are owned by
`local/projects/teleclaude/design/architecture/runtime-acceptance/finalization`.
Independent review separates assertion authorship from implementation and
qualification (`general/principle/verification-independence`).

## Inputs/Outputs

Input is an independently reviewed static lock and concrete provisioning recipe,
bound to exact controller/helper/unit bytes and candidate commit/tree. The lock
contains no unresolved value at execution. A setup result records observed
host/package/namespace/activation/observation facts and the exact lock/recipe
identity. It is separate from the application profile and its final aggregate.

### Static lock completeness

| Binding group           | Required evidence                                                                                                                                                                                                                                                                                                                      |
| ----------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Host compatibility      | Architecture and explicit accepted runner-image/kernel/systemd/package tuples; executable/interpreter identities; actual runner account is discovered and recorded rather than inferred from the guest UID.                                                                                                                            |
| Signed package inputs   | Fixed snapshot/pocket/component/architecture; signed Release/InRelease bytes, digest, trusted key fingerprint and verification result; each selected index path/size/digest; complete host and guest package dependency closure with versions, alternatives, archive addresses/sizes/digests and maintainer-script/activation effects. |
| Guest base and tools    | Exact archive and independently authenticated checksum/signature/key chain; base package inventory; locked Python distribution/patch/build, uv binary and all installer/native dependencies. Floating archives, package upgrades and host PID-1 replacement are excluded.                                                              |
| Effective manager graph | Distro-installed vendor template bytes, all dependency units/drop-ins/settings and activation sources; complete host instance and parent recipe, guest payload/poweroff units, accounts/sudo/user-manager/network setup and actual effective-property predicates. An upstream template is not a distro-file digest.                    |
| Harness and evidence    | Controller/helper code and interpreter digests, closed privileged action vocabulary, source commit/tree and clean guest checkout, argv/environment/cwd recipe, role discriminator, report/export map, budget declaration and qualification assertions.                                                                                 |

Signatures authenticate vendor inputs, not the author's lock or future host
behavior. Every lock/recipe change is reviewed independently and invalidates
qualification bound to earlier bytes. Source implementation review separately
binds the realized helpers/units and their effective graph before any privileged
qualification; a completed field or version string alone supplies no approval
(`sdlc/policy/security-awareness`).

## Invariants

### One owner, one invocation

The outside supervisor runs on a disposable hosted VM and never executes product
or native fixture work. It owns a unique run directory, machine/rootfs, parent
slice, nspawn instance, drop-ins, runtime mask, observation handles and reports.
Workflow/run attempt plus fresh nonce, source/tree, controller start identity
and host boot/manager generation bind all of them. Ownership and a fsynced safe
recovery prefix precede privileged effects. Foreign paths or same-name retained
objects are collisions, never reusable fixtures.

Privileged setup uses a source-reviewed action interface in the same harness.
It verifies code/interpreter/run/path/action identities and journals each intent
before the manager call and its actual outcome afterwards. It accepts no shell
text or arbitrary application command. It starts at most the one guest and one
payload, accounts for helpers and permanently closes its start admission before
physical observation. Unknown acknowledgments are not retried.

### Concrete provisioning recipe

Offline rootfs assembly uses the locked packages and inspected no-service-start
policy. It binds no host home, credentials, system/user bus or system manager
socket. Package maintainer scripts cannot leave an unclassified host creator.
The host's existing manager is never upgraded or restarted to make a tuple fit.

The host manager creates and starts one unique parent slice with automatic
unneeded stopping disabled. Bind its public ControlGroup and observation
handles/monitor before the single nspawn instance is started beneath it. Use
the locked installed vendor boot/delegation invocation, with instance-only
drop-ins: parent placement, no ordinary restart, and an explicitly empty forced
restart-status set. Clearing ordinary restart alone is insufficient.

After boot and before payload, verify the same manager/parent/service invocation,
actual effective graph and guest placement. Mask that exact active instance
without stopping it, verify it stayed in the same invocation, reconcile all
already accepted jobs/activators, and seal host admission. No alias, host helper
or other unit can start profile work or reenter the retained rootfs after that
seal. A job listing is supporting evidence inside this protocol, never its fence.

Guest PID 1 and every system/user manager remain inside the delegated subtree.
Require a positively verified non-identity user namespace and its actual UID/GID
maps, supported cgroup namespace/delegation and report/source ownership. A
namespace fallback or unsupported observation primitive fails before payload.
The guest account is ordinary `runner`, UID/GID 1001, with its own home, user
bus/logind setup and guest-only noninteractive sudo. Its OS privilege grants no
host access or application caller standing. Actual mappings never assume the
host runner also has UID 1001.

The payload unit is not boot-enabled. It runs the same full-profile public entry
as the ordinary guest account from the checked candidate, with explicit payload
role, source/tree, selected scenarios and owned report address. Its login
environment, PATH, tools and user bus are statically declared and qualified.
It has no ordinary or forced restart. Success and failure activate one guest
root cleanup unit that delegates to the same harness module, records available
phase/report facts and requests poweroff asynchronously without waiting for its
own shutdown. Declarations carry no inline logic (`sdlc/policy/no-inline-logic`).

Product installation and lifecycle use the existing installer and make targets
inside the guest. Their real daemon/tmux/watch/cron/dependency definitions remain
intact (`local/projects/teleclaude/policy/agent-service-control`). The enclosure
manager interface is confined to this disposable test guest; agents do not use
it for live daemon control. Raw cgroup writes, process migration, kill-to-pass,
private application imports and substituted authentication are excluded.

### Observation and result binding

Original-handle reads and continuous manager/cgroup observation start before
boot and continue through witness sealing. The monitoring recipe specifies
descriptor lifecycle, generation/invocation identity, removal/movement and
overflow/disconnect detection. Reconnection or same-name reopen does not restore
lost continuity. The finite qualification below proves these actual semantics;
stat equality and a source citation do not.

The report map distinguishes CI's checked revision/tree from the immutable
release candidate's commit/tree, and each workflow's primary prefix. Witness
and recovery siblings are explicit additive paths. Existing candidate files,
B13 and other separately authorized sidecars retain their exact mappings and
guards. Snapshot acquisition modes and B14 behavior require their own authority.

## Primary flows

### Static preparation and source review

1. Freeze the complete signed static inputs and concrete unit/helper/configuration
   recipes, including all activation and account/network/ownership effects.
2. Independently review the owning contract, separate finalization amendment,
   locks, recipes and finite qualification assertions before implementation.
3. Implement only that reviewed contract in the one harness. Review the exact
   source SHA, all starts/exceptions, privilege and admission paths, report types,
   observation and resource-release paths. Bind realized bytes back to the lock.
4. Record separate authorization for the finite setup attempt at that SHA and
   lock. No setup action is implied by a design or source approval.

### Finite operational setup qualification

One explicitly authorized attempt runs only the following OS/harness assertions
with no TeleClaude workload, API call, session record or seeded authentication.
It creates one measurement guest and separately named disposable diagnostic
objects for destructive observation checks. The latter are never the production
measurement parent. Each row reports its own observed result or unexecuted state.

| ID  | Action and observable expected result                                                                                                                                                                                                                                                                                           |
| --- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Q1  | Verify signed locks against actual host tuple/packages/template/helper bytes and privilege. Any mismatch stops before guest/workload; there is no upgrade/restart or floating-version fallback.                                                                                                                                 |
| Q2  | Provision the locked empty guest and bind the original active parent before one boot. Record manager generation, ControlGroup, invocation, complete effective graph, namespaces/maps, account/bus/network/tools and actual ownership. Unsupported or unknown facts prevent payload admission.                                   |
| Q3  | Apply the exact active-instance mask with no stop, reconcile queued starts/aliases/activation sources and seal admission. Verify unchanged invocation and no later start action. An accepted or ambiguous start after sealing fails qualification; no retry supplies a second invocation.                                       |
| Q4  | Put inert OS descendants under guest system/user managers and a long-lived shell within the measured subtree, then shut down normally. Observe verified poweroff, unchanged original active parent, closed admission and recursive empty population through the original handle. No application lifecycle fact is manufactured. |
| Q5  | On separate diagnostic objects, exercise removal/recreation, movement/deactivation and observation disconnect/overflow or equivalent lost-continuity inputs. Every loss yields unproven, including a same-name replacement that is empty. The measurement handle is never rebound.                                              |
| Q6  | End a setup phase unexpectedly and exercise one lost start acknowledgment plus missing/corrupt report/readback/export failures in harness-owned OS diagnostics. Preserve prewritten intent, original error and verified prefix; no second start, final pass or unsafe resource release occurs.                                  |
| Q7  | Run two distinct setup owners and a colliding run identity. Distinct resources remain disjoint; collision is refused before privileged mutation, and foreign resources remain untouched.                                                                                                                                        |
| Q8  | Bound a clean setup shutdown/export and one expired-budget attempt. Measure actual durations, preserve partial diagnostics on expiry and verify every phase uses remaining outer time, with no force-kill-to-pass or automatic retry.                                                                                           |

The qualification declaration assigns finite per-row and command budgets within
one monotonic outer deadline no greater than the workflow runtime step. It
reserves five minutes within that existing cap for shutdown/evidence, rather
than adding time to the step. A setup command has at most 120 seconds, guest
boot/closure at most 300 seconds each; the outer remaining budget always wins.
Each diagnostic vector runs once, in a distinct namespace where needed. No
unbounded repetitions, automatic compatibility updates or attempts to repair the
host are part of qualification. Insufficient remaining time prevents a new row.
Actual provisioning and complete-attempt fit are measured, never inferred from
these limits. Failure retains bounded diagnostics and returns for independent
disposition before another attempt.

### Installation and acceptance

After setup qualification, separately authorized existing installation and
selected/full profiles execute against the independently reviewed source and
qualified lock. Installation fidelity, actual P1–P4, failure export, resource
release and total timing are observed there. Setup success supplies none of
those application facts. A selected profile supplies no full-profile credit,
and the final immutable candidate still requires its full installation proof.

## Failure modes

- Incomplete signed dependency closure, unreviewed scripts/templates/helpers or
  effective activation drift blocks implementation/qualification admission at
  the corresponding gate. Metadata availability is not lock completeness.
- A creator outside the measured denominator, identity/namespace fallback,
  replaced manager or observation gap invalidates containment. A smaller empty
  subtree does not excuse it.
- Start uncertainty, timeout or report corruption preserves original facts and
  ends the attempt; same-run recovery never retries starts or changes substrate.
- Runtime image drift can make preflight fail. A compatible replacement tuple
  requires independently reviewed static locks and a new qualification attempt.

## See Also

- docs/local/design/architecture/runtime-acceptance/finalization.md
- docs/local/spec/feature/agent_runtime/runtime-acceptance.md
