# Infrastructure Relocation & Node Roles — Investigation

> Durable scratch. **Not a todo.** This captures a vision + open questions we want to
> continue without losing, not committed work. When appetite comes, concrete todos spin
> off from here — this note stays as the reasoning behind them.
> Last updated: 2026-07-07.

## Read this first — the frame (so nobody re-imports the wrong model)

These three computers are **heterogeneous, unique machines with assigned duties** — not
identical cluster replicas. Do **not** reason about this with database-quorum / leader-
election / Raft / Redlock mental models. That is homogeneous-replica thinking and it does
not fit.

- "Master" here has **never** meant a quorum leader. In live code `computer.is_master`'s
  _only_ effect is "this box owns provisioning the singular shared Discord surfaces."
- **Failover ≠ replica takeover.** There is no equivalent node to fail a workload over to —
  each box is unique (one is infra-only).
- The real goal is **uptime via straightforward relocation**, not high availability via
  consensus. Accepted model: _a box dies → its apps go down → I relocate them to a capable
  box._ Downtime on crash is acceptable. The only "non-availability" case that matters is
  "my computer died."

The fleet today: **MozBook**, **MozMini** (role "AI Server"), **Raspi** (currently the
ingress node). Raspi is running on an old, flaky SD card and is **expected to die soon** —
this is the pressing driver behind everything below.

## Disentangling the conflated concerns

Five distinct things got braided together in conversation. They should be treated
separately.

### A. PRESENT BUG — Discord duplicate shared channels (`customer-sessions-channel-master-only`)

In-flight, at plan phase. Root cause is **duty double-assignment**: two boxes (MozBook +
MozMini) both carry the `is_master` Discord-shared-provisioning duty, and nothing prevents a
second box from also claiming it → both create the `Customer Sessions` forum (4 observed).
ADR 0012 explicitly anticipated this ("Two masters reintroduce the race"). This is **not a
consensus failure** and must **not** be entangled with the vision below.

- Minimal resolution (proposed, not yet finally ratified): operational fix (designate one
  owner + delete the 3 duplicate forums) + a cheap boot-time **collision alarm** (if I'm the
  owner and a live peer heartbeat also advertises the duty → refuse-to-create + escalate) +
  excise the dead Telegram-admin `is_master` surface + retire the stale master-bot docs.
- Ships on its own. Parked at plan phase pending return.

### B. SMALL CLEANUP — env-var duplication (`SSH_HOST` vs `ITSUP_HOST`)

An agent duplicated the variable; `SSH_HOST` should converge onto the existing `ITSUP_HOST`.
Lives in the **itsup project (separate repo)** — no refs in TeleClaude. Concrete, small, its
own thing. Connects to the vision only via C3 below.

### C. THE VISION — relocatable heterogeneous infrastructure (this is the real thing)

Everything else is sub-threads of one goal: **move my infrastructure off the dying Pi onto
the Mac Mini easily, and distribute load across unique boxes.**

- **C1 — The driver.** Raspi is full + failing (old SD card). Need to move load off it
  _before_ it dies. This is the only prevalent availability use case.
- **C2 — Crown-jewels relocation.** The "crown jewels" are the **projects repo** and the
  **secrets repo**. Want a straightforward way to relocate (and possibly _merge_) these onto
  MozMini — possibly as separate MozMini projects/secrets repos, potentially merged into one
  new platform. This is the thing you actually want most: an easy "pick it up and move it"
  path.
- **C3 — Runtime infra-host determination.** A computer that declares
  `SSH_HOST`/`ITSUP_HOST` = its own local IP is, _at runtime_, determined to be "the real
  host running the infrastructure." So **which box is the infra host is a runtime/env fact,
  not a static config flag.** (This is why B is not just cosmetic — the var is load-bearing
  for relocation.)
- **C4 — Ingress / TLS topology.** Ingress (traffic/webhook termination) is Raspi today.
  Vision: **TLS pass-through** from the first traffic instance to a second instance that does
  termination at the second node → a hybrid. Ingress is its own relocatable duty
  (`is_ingress_node` already exists, separate from `is_master`; ADR 0028/0055 already state
  "the ingress need not be the master").
- **C5 — Does "master" even survive?** Open architectural question you raised: _maybe there
  is no "master" concept when you distribute load over infra nodes._ `is_master` today is
  just "Discord-shared-provisioning owner." Candidate directions (undecided):
  1. **Decompose** the coarse `is_master` into explicit, individually-relocatable **per-duty
     owner** designations (discord-shared owner, ingress owner, infra-host, …), each assigned
     to one capable box — mirroring how `is_ingress_node` already works.
  2. **Fold** duty-ownership into the runtime infra-host determination (C3), so env/runtime
     facts drive it rather than static flags.
  3. **Retire** "master" as a concept entirely.
- **C6 — Parked sub-idea (clearly subordinate).** _If_ any duty ever needs **automatic**
  successor-on-death (not just manual relocation), the only viable substrate is **Redis as an
  atomic-lease referee** (`SET NX EX`) — heartbeats are **detection-only**, never a consensus
  primitive. But your stated need is _manual, straightforward relocation_, so this may never
  be needed. Do not build toward it unless a real auto-takeover requirement appears.

### C6 opening scope — grounding from the `customer-sessions-channel-master-only` bug (agent-authored, 2026-07-07)

The Discord duplicate-channels bug tried to enforce the single-master invariant with a
runtime guard and hit exactly the wall this section names. Captured so the peer-state work
starts from grounded code, not from scratch. (The bug itself is resolved operationally; see
its `log` artifact.)

**Why a cache/heartbeat guard cannot be correct (the wall):**

- The only cross-computer state is the Redis heartbeat. It feeds the **DaemonCache**
  (`teleclaude/core/cache.py:106`, `get_computers()` at `:285`), populated by
  `_refresh.refresh_peers_from_heartbeats` → `cache.update_computer` (`_refresh.py:267-278`,
  `cache.py:463-470`).
- At Discord `on_ready` (where shared-channel provisioning runs, `infra.py:154`), the cache is
  **empty and ambiguous**: `on_ready` and the initial peer sync (`_populate_initial_cache` →
  `refresh_remote_snapshot`) are **unsynchronized background tasks** — no barrier
  (`_client.py:191` vs `:202`, `_connection.py:150-163`). Empty ≠ "no peers"; it can mean
  "peers haven't reported yet."
- `get_computers()` applies **no read-time TTL filter** and **never prunes dead peers**
  (`cache.py:285-294`) — so it can also report a long-dead master as present. Liveness is only
  the upstream Redis key TTL (heartbeat interval **30s**, TTL **60s**, hardcoded in
  `_transport.py:113-114`).
- Net: a cache-based guard can only **fail open** (both masters create — the original bug) or
  **fail closed** (a legitimate sole master refuses to provision on cold start). ADR-0012
  already rejected timing/locking dedup as best-effort. The clean resolution is a **lease**:
  the master is whoever holds `SET master-lease <node> NX EX <ttl>` and renews it; the lease
  _is_ the single-writer guarantee, replacing the `is_master` flag.

**Reusable opening pieces (not throwaway):** advertising `is_master` on the heartbeat is the
one piece worth keeping — add `is_master: bool` to `ComputerInfo` (`_snapshot.py:272`), the
heartbeat payload (`_heartbeat.py:69`), and the ingest at `_refresh.py:267`; for cold-start
parity also `PeerInfo` (`_adapter.py:44`), `_build_peer_info` (`_peers.py:200`), and the
`PeerInfo→ComputerInfo` copy (`_refresh.py:101`). But the _decision_ must be lease-backed, not
cache-guessed. And it should be **per-duty** (Discord-shared-owner, ingress-owner, …), not one
global "master" — consistent with C5 and the existing `is_ingress_node` precedent.

## Coherent approach (recommendation)

1. **Ship A now, decoupled.** The Discord bug is a config/duty-assignment defect; resolve it
   minimally. It is not the vision.
2. **B when convenient** — a small dedupe in the itsup project.
3. **Keep C as this investigation.** The unifying reframe: **stop thinking "master /
   failover," start thinking "named per-duty ownership + straightforward relocation of duties
   and crown-jewel data across heterogeneous boxes, with accepted downtime on crash."**
   - The first concrete todo, when appetite comes, is almost certainly **"relocate
     projects + secrets to the Mac Mini"** (the pressing Pi-death driver) — a migration
     runbook, not an HA system.
   - Separately, later: **"decide the fate of `is_master`"** (decompose into per-duty owners
     / fold into runtime infra-host / retire). Design pass + likely an ADR superseding 0012.

## Open questions to resume with

- Do projects & secrets become **separate MozMini repos**, or **merge into one new
  platform**? (Your musing — undecided.)
- Does `is_master` get **decomposed**, **folded into the runtime infra-host (`SSH_HOST`)**,
  or **retired**?
- Is the **TLS-passthrough hybrid** the standing topology, or only a migration-time bridge?
- What does the **minimum "relocate everything to the Mini" runbook** look like? ← the thing
  you actually want.

## Grounding anchors (for whoever picks this up)

- ADR 0012 — master-only shared Discord provisioning (the duty `is_master` actually gates);
  it explicitly deferred election as premature and named the two-master race.
- `is_ingress_node` flag + ADR 0028 / ADR 0055 — ingress is its own relocatable duty,
  independent of master; precedent for per-duty ownership flags.
- Config `people` lives in **`GlobalConfig`** (shared across the fleet, not per-computer) —
  relevant if per-computer permission isolation ever becomes a goal.
- One cluster-bus Redis (ADR 0032); heartbeat substrate at
  `teleclaude/transport/redis_transport/_peers.py` (`computer:*:heartbeat`, `last_seen`) —
  detection/liveness only.
- **itsup project (separate repo)** — `SSH_HOST`/`ITSUP_HOST` → runtime infra-host. Must be
  read there to ground C2/C3; not present in TeleClaude.
- Stale docs to retire when A ships: `project/concept/master-bot`,
  `project/policy/master-bot-registration` (describe a `telegram.is_master`-gated
  `setMyCommands` that exists in neither config nor code — Telegram-as-admin-adapter is dead).
