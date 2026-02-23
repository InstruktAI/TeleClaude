# Demo: inbound-hook-service

## Validation

```bash
# Verify daemon starts with inbound endpoints mounted
make status
instrukt-ai-logs teleclaude --since 60s --grep "inbound endpoint"
```

```bash
# Verify GitHub normalizer is registered
instrukt-ai-logs teleclaude --since 60s --grep "normalizer"
```

```bash
# Send a test GitHub push webhook and verify it's accepted
# (requires daemon running with hooks.inbound.github configured)
curl -s -X POST http://localhost:9224/hooks/inbound/github \
  -H "Content-Type: application/json" \
  -H "X-GitHub-Event: push" \
  -H "X-Hub-Signature-256: sha256=$(echo -n '{"ref":"refs/heads/main","repository":{"full_name":"test/repo"},"sender":{"login":"testuser"}}' | openssl dgst -sha256 -hmac 'test-secret' | awk '{print $2}')" \
  -d '{"ref":"refs/heads/main","repository":{"full_name":"test/repo"},"sender":{"login":"testuser"}}' \
  | python3 -c "import sys,json; d=json.load(sys.stdin); assert d['status']=='accepted', f'Expected accepted, got {d}'; print('OK: webhook accepted')"
```

```bash
# Verify unit tests pass
make test -- -k "test_github_normalizer"
```

## Guided Presentation

### Step 1: Show the daemon logs

Restart the daemon and observe that inbound endpoints are now mounted during webhook service initialization.

**What to observe:** Log lines showing `Registered inbound endpoint: /hooks/inbound/github` and `Registered normalizer: github`.

**Why it matters:** This proves the `InboundEndpointRegistry` and `NormalizerRegistry` are wired into the daemon startup path — the core fix this todo delivers.

### Step 2: Send a GitHub push webhook

Use `curl` to POST a simulated GitHub push event to the inbound endpoint. Include the `X-GitHub-Event: push` header and a valid HMAC signature.

**What to observe:** HTTP 200 response with `{"status": "accepted"}`. Daemon logs show the normalizer processing the payload and producing a `HookEvent(source="github", type="push")`.

**Why it matters:** End-to-end proof that external webhooks enter TeleClaude and flow through the contract-matching pipeline.

### Step 3: Demonstrate HMAC rejection

Send the same payload with an invalid signature.

**What to observe:** HTTP 401 with `"Invalid signature"`. The payload never reaches the normalizer.

**Why it matters:** Security gate — unsigned or tampered webhooks are rejected before any processing.

### Step 4: Show the GitHub normalizer output

Walk through a `push` event and a `ping` event. Show the `HookEvent` properties extracted from each.

**What to observe:** `push` produces `type="push"`, `properties.repo="owner/repo"`, `properties.sender="username"`, `properties.ref="refs/heads/main"`. `ping` produces `type="ping"`, `properties.zen="..."`.

**Why it matters:** The normalizer transforms platform-specific payloads into the canonical `HookEvent` format that the rest of the hook service understands.

### Step 5: Show path derivation

Demonstrate that removing the `path` field from a config entry causes the system to derive `/hooks/inbound/{source_name}` automatically.

**What to observe:** Config without explicit path still mounts the endpoint at the conventional path.

**Why it matters:** Convention over configuration — users don't need to think about paths for standard integrations.
