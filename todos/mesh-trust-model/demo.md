# Demo: mesh-trust-model

## Validation

```bash
# 1. Trust ring SQLite tables exist after daemon start
sqlite3 ~/.teleclaude/teleclaude.db ".tables" | grep -q trust_peers && echo "PASS: trust_peers table exists"
sqlite3 ~/.teleclaude/teleclaude.db ".tables" | grep -q trust_observations && echo "PASS: trust_observations table exists"
```

```bash
# 2. Trust ring API responds
curl -s --unix-socket /tmp/teleclaude-api.sock http://localhost/api/trust/ring | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'PASS: ring has {len(d)} peers')"
```

```bash
# 3. Add a peer to the trust ring
curl -s --unix-socket /tmp/teleclaude-api.sock -X PUT http://localhost/api/trust/ring/node-test-123 \
  -H 'Content-Type: application/json' -d '{"trust_level":"trusted"}' | python3 -c "import sys,json; print('PASS: peer added' if json.load(sys.stdin).get('trust_level')=='trusted' else 'FAIL')"
```

```bash
# 4. Verify peer appears in ring
curl -s --unix-socket /tmp/teleclaude-api.sock http://localhost/api/trust/ring | python3 -c "import sys,json; peers=json.load(sys.stdin); print('PASS: peer in ring' if any(p['peer_id']=='node-test-123' for p in peers) else 'FAIL')"
```

```bash
# 5. Remove the test peer
curl -s --unix-socket /tmp/teleclaude-api.sock -X DELETE http://localhost/api/trust/ring/node-test-123 && echo "PASS: peer removed"
```

```bash
# 6. Tests pass
make test 2>&1 | tail -5
```

## Guided Presentation

### Step 1: The trust evaluator in the pipeline

Show that the trust evaluator cartridge is registered in the event pipeline chain.

```
Open teleclaude_events/trust/evaluator.py and show the TrustEvaluator class.
Show the pipeline wiring where the cartridge is inserted: dedup → trust → notification.
```

**What to observe:** The evaluator conforms to the Cartridge protocol. It's positioned
after dedup (so duplicate events are already filtered) and before notification (so
untrusted events never reach the notification database).

**Why it matters:** This is the immune system — every mesh event passes through it.
Local events bypass entirely. The pipeline order enforces the security boundary.

### Step 2: Trust never travels

Demonstrate that trust evaluation is purely local.

```
Show TrustDB — the trust_peers and trust_observations tables.
Show that trust records are never included in event envelopes.
Show that observation events (trust.flagged etc.) have visibility: local.
```

**What to observe:** The trust ring is SQLite-local. Observation events stay local.
No trust data appears in outbound event envelopes. A node's trust opinions are its
own business.

**Why it matters:** This is the cornerstone security property. There's no trust
ledger to hack, no reputation score to manipulate, no trust propagation chain to
exploit.

### Step 3: Sovereignty configuration

Show the YAML config surface for trust settings.

```
Show the trust: section in the TeleClaude config.
Demonstrate sovereignty levels per domain (L1/L2/L3).
Show mute/trust list configuration.
```

**What to observe:** Simple YAML config that gives the operator full control over
how their node evaluates events. Default is L1 (human-in-loop) — maximum caution.

**Why it matters:** Sovereignty means freedom AND responsibility. The platform
provides handles, not mandates.

### Step 4: Death by loneliness

Show how muted sources are handled.

```
Add a source to the mute list.
Send a test event from that source through the pipeline.
Show that it's dropped silently — no notification, no response.
```

**What to observe:** The muted source's event is dropped at the trust cartridge.
It never reaches the notification database. No error, no response, no attention.

**Why it matters:** Bad actors aren't banned (that requires authority). They're
ignored. The mesh doesn't fight spam — it simply doesn't care about it.

### Step 5: Trust ring in action

Show the trust ring management API.

```
List the ring (empty initially).
Add a peer as trusted.
Show that events from trusted peers get streamlined evaluation.
Remove the peer.
Show observation history.
```

**What to observe:** Trust ring members get faster processing. Adding/removing
peers emits local observation events. The ring is the node's inner mesh.

**Why it matters:** Trust rings form organically through successful interactions,
exactly like human friendships. The API gives operators explicit control.
