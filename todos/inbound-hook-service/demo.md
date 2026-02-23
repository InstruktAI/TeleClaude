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
# NOTE: Requires a running daemon with hooks.inbound.github configured in teleclaude.yml.
# Cannot execute in build environment (no daemon running).
# End-to-end coverage is provided by tests/integration/test_inbound_webhook.py.
echo "SKIP: live curl demo requires running daemon — covered by integration tests"
```

```bash
# Verify unit tests pass
uv run pytest tests/unit/test_github_normalizer.py tests/integration/test_inbound_webhook.py -q
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
