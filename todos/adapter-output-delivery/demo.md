# Demo: adapter-output-delivery

## Validation

```bash
# Verify _NON_INTERACTIVE no longer blocks HOOK origin
python3 -c "
import ast, sys
with open('teleclaude/core/adapter_client.py') as f:
    tree = ast.parse(f.read())
for node in ast.walk(tree):
    if isinstance(node, ast.Assign):
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == '_NON_INTERACTIVE':
                elts = [e.attr for e in node.value.elts if isinstance(e, ast.Attribute)]
                if 'HOOK' in [e.split('.')[-1] if '.' in e else e for e in elts]:
                    print('FAIL: HOOK still in _NON_INTERACTIVE')
                    sys.exit(1)
                # Check via string representation
                src = ast.dump(node.value)
                if 'HOOK' in src:
                    print('FAIL: HOOK still in _NON_INTERACTIVE')
                    sys.exit(1)
                print('PASS: HOOK removed from _NON_INTERACTIVE')
                sys.exit(0)
print('FAIL: _NON_INTERACTIVE not found')
sys.exit(1)
"
```

```bash
# Verify trigger_incremental_output method exists on AgentCoordinator
grep -q 'async def trigger_incremental_output' teleclaude/core/agent_coordinator.py \
  && echo "PASS: trigger_incremental_output exists" \
  || { echo "FAIL: trigger_incremental_output not found"; exit 1; }
```

```bash
# Verify broadcast_user_input is called before non-headless early return
python3 -c "
import re, sys
with open('teleclaude/core/agent_coordinator.py') as f:
    src = f.read()
# Find handle_user_prompt_submit method body
match = re.search(r'async def handle_user_prompt_submit.*?(?=\n    async def |\nclass )', src, re.DOTALL)
if not match:
    print('FAIL: handle_user_prompt_submit not found')
    sys.exit(1)
body = match.group()
# broadcast_user_input must appear BEFORE the non-headless return
bc_pos = body.find('broadcast_user_input')
ret_pos = body.find('lifecycle_status != \"headless\"')
if bc_pos < 0:
    print('FAIL: broadcast_user_input not called in handle_user_prompt_submit')
    sys.exit(1)
if ret_pos < 0:
    print('FAIL: non-headless guard not found')
    sys.exit(1)
if bc_pos < ret_pos:
    print('PASS: broadcast_user_input called before non-headless return')
else:
    print('FAIL: broadcast_user_input called after non-headless return')
    sys.exit(1)
"
```

```bash
# Verify agent_coordinator is wired to adapter_client
grep -q 'agent_coordinator' teleclaude/core/adapter_client.py \
  && echo "PASS: agent_coordinator reference exists on adapter_client" \
  || { echo "FAIL: agent_coordinator not wired to adapter_client"; exit 1; }
```

```bash
# Verify poller triggers incremental output
grep -q 'trigger_incremental_output' teleclaude/core/polling_coordinator.py \
  && echo "PASS: poller triggers incremental output" \
  || { echo "FAIL: poller does not trigger incremental output"; exit 1; }
```

```bash
# Tests and lint pass
make test && make lint
```

## Guided Presentation

### Step 1: The text delivery gap (before)

Open a Claude session with Discord threaded output enabled. Ask Claude to perform a multi-step task (e.g., "read three files and summarize each"). Observe: Discord only shows output at tool-call boundaries. Text written between tools is invisible until the next tool call or agent stop.

### Step 2: The fix — poller-triggered incremental output

After the fix, the poller's `OutputChanged` handler calls `trigger_incremental_output` on every output change. For threaded sessions, this triggers `_maybe_send_incremental_output`, which parses the transcript and sends any new text since the last cursor. Non-threaded sessions fast-reject with no I/O cost.

**Observe:** Discord now shows text between tool calls within ~2s of appearing in the transcript.

### Step 3: The user input gap (before)

In a terminal session with Discord connected, type a message. Observe: the input is processed by the agent but never appears in Discord. The non-headless early return at line 426-427 skips `broadcast_user_input`. For headless sessions via hooks, `_NON_INTERACTIVE` blocks `HOOK` origin.

### Step 4: The fix — input reflection

After the fix: (a) `broadcast_user_input` is called before the non-headless return, and (b) `HOOK` is removed from `_NON_INTERACTIVE`. Terminal input now appears in Discord/Telegram as "TUI @ {computer_name}:\n\n{text}". MCP-origin input remains correctly filtered.

**Observe:** Type in the terminal — the message appears in Discord within seconds with source attribution.

### Step 5: Negative case — MCP input stays filtered

Send a message via MCP origin. Verify it does NOT appear in Discord/Telegram. The `_NON_INTERACTIVE` filter still blocks `InputOrigin.MCP.value`.
