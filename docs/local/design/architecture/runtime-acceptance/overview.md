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

The static input is the authenticated vendor closure in `static-lock.json` and
the exact declarative unit/configuration/helper protocol in
`enclosure-recipes.json`. Those files own their concrete values and byte
identities. Future helper implementation bytes are not a static-stage input.

After implementation, a separate source-realization record binds the actual
candidate commit/tree, controller/helper/interpreter/library bytes, rendered
units and report schemas to that reviewed static package. Exact-SHA source
review judges this realization before qualification. Qualification consumes
both records, its separately reviewed `qualification.json` and separate run
authorization. Results add observed host/package/namespace/activation and
observation facts; static review supplies none of those runtime identities.

### Installation input classes

`static-lock.json` classifies the complete input contract: fixed enclosure/OS
substrate, source-locked project environments, and product-owned rolling tool
installation. The classes have different identity times; an unconstrained
independent tool environment is never described as constrained by the project
lock. Installation retains its own supported selection and setup path
(`local/projects/teleclaude/spec/feature/reconciliation/fresh-machine-bootstrap`).

The static gate binds complete substrate/source locks and the concrete rolling
observation recipe before implementation. The rolling tool's actual resolved
distributions, interpreter and emitted activation assets are run observations,
not missing future hashes certified at preparation. The recipe owns their
required metadata, installed-byte identities, containment and evidence limits;
unavailable or incomplete facts remain unknown and block acceptance. No
collector pins, skips, preinstalls in place of the rolling operation, changes
its index/constraints or mutates its managed environment. The shared tool's
setup and dependency semantics remain its owner's
(`general/principle/verification-independence`).

Every product installer process, rolling tool, build helper, user scheduler and
rotator executes inside the already established guest boundary. Physical P4
covers that complete subtree independently of package versions or a finite
static unit list. Actual activation observations finish before P3. A changed
fixed substrate or an uncontained creator invalidates the corresponding proof;
unknown receipts, effects and lifecycle facts keep their separate blocking
force. Setup qualification executes none of these product operations and
supplies no rolling-installation evidence.

### Static lock completeness

| Binding group           | Required evidence                                                                                                                                                                                                                                                                                                                                         |
| ----------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Host compatibility      | Architecture and explicit accepted runner-image/kernel/systemd/package tuples; executable/interpreter identities; actual runner account is discovered and recorded rather than inferred from the guest UID.                                                                                                                                               |
| Signed package inputs   | Fixed snapshot/pocket/component/architecture; signed Release/InRelease bytes, digest, trusted key fingerprint and verification result; each selected index path/size/digest; complete declared host and guest bootstrap package dependency closure with versions, alternatives, archive addresses/sizes/digests and maintainer-script/activation effects. |
| Guest base and tools    | Exact archive and independently authenticated checksum/signature/key chain; base package inventory; locked Python distribution/patch/build, uv binary and all installer/native dependencies. Floating archives, package upgrades and host PID-1 replacement are excluded.                                                                                 |
| Effective manager graph | Distro-installed vendor template bytes, all dependency units/drop-ins/settings and activation sources; complete host instance and parent recipe, guest payload/poweroff units, accounts/sudo/user-manager/network setup and actual effective-property predicates. An upstream template is not a distro-file digest.                                       |
| Harness and evidence    | Declared controller/helper entry and closed action protocol, authenticated interpreter/library inputs, dependency-basis source locks, argv/environment/cwd recipe, role discriminator, report/export map and finite qualification declaration. Actual implementation commit/tree and code digests belong to the subsequent realization record.            |

Signatures authenticate their named vendor inputs, not the author's JSON or
future host behavior. Integrity-only and attested inputs retain their explicit
authentication classes in the lock. Every lock/recipe change is independently
reviewed before implementation against it and invalidates earlier qualification.
Source review binds actual helpers and rendered units through the separate
realization record; it does not retroactively complete a missing static recipe
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
The ordinary guest account is defined by `guest.account` in
`enclosure-recipes.json`, with its own home, user bus/logind setup and
namespace-confined noninteractive sudo. Its OS privilege grants no host access
or application caller standing. Actual mappings never equate the configured
guest identity with the host account.

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

The report map includes the rolling-input observations defined by the recipe and
distinguishes CI's checked revision/tree from the immutable
release candidate's commit/tree, and each workflow's primary prefix. Witness
and recovery siblings are explicit additive paths. Existing candidate files,
B13 and other separately authorized sidecars retain their exact mappings and
guards. Snapshot acquisition modes and B14 behavior require their own authority.

## Primary flows

### Static preparation and source review

1. Freeze the static lock, concrete recipe and finite assertion files, including
   vendor signatures/integrity, complete dependency sets, activation sources,
   account/network/ownership declarations and selected monitoring primitives.
2. Independently review those exact artifacts with the owning contract and
   separate finalization amendment before implementation. No future source hash
   is required or represented as existing at this gate.
3. Implement only that reviewed package in the one harness. Produce the distinct
   source-realization record. Review the exact source SHA, starts/exceptions,
   privilege/admission paths, report types, notification and resource-release
   paths, including agreement between emitted bytes and static declarations.
4. Record separate authorization for one finite setup attempt at the approved
   realization and static package. A changed recipe returns through preparation
   review; source review cannot silently replace it. No setup action is implied
   by either earlier approval.

### Finite operational setup qualification

`qualification.json` owns the closed vector order, concrete action lists,
observation authority, required retained facts, per-vector and per-command
budgets, resource inventory and total deadline. It permits no equivalent-vector
substitution. Each vector executes at most once; an unexpected result ends the
attempt after bounded declared closure/read/export, and later vectors remain
unexecuted. Another attempt requires independent disposition and separate
authorization (`general/principle/verification-independence`).

Qualification executes only OS/harness facts: one empty measurement guest and
explicitly named inert diagnostic objects, without a product installer, API,
session record or authentication seed. Diagnostic removal/recreation never
rebinds the measurement parent. Kernel queue overflow is observed on a separate
owned filesystem queue; it supplies no claim that a cgroup was moved. Source
review covers every specified invalidation handler independently of which
physical events the finite declaration exercises.

Q1 performs read-only admission and authenticates the actual required fixed-input
bytes before Q2. Q2 consumes those authenticated offline inputs; fixed addresses
and expected digests alone supply no actual-byte authentication. Its outside
package control-script execution is confined to the conditional host transaction
declared by `enclosure-recipes.json` `host.host_changes` and `static-lock.json`
`host_closure.policy`, with the reviewed source/effect/creator scope and strict
final package predicates preserved (`general/principle/verification-independence`).

The qualification deadline and closure/export reserve are explicit declarations,
not measured fit. Every action consumes the least remaining vector, command or
outer allowance. Expired allowance prevents another action. No host repair,
floating-version update, automatic retry or force-kill-to-pass belongs to the
attempt. Actual provisioning/shutdown/export fit and all effective host facts
remain operational results obtained only under separate authorization.

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
