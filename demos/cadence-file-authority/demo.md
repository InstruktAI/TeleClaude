# Demo Plan — cadence-file-authority

## Medium

CLI + log inspection. The changes are in the rendering pipeline — the observable behavior
is identical output delivery with a simpler, file-derived authority model. The demo verifies
structural properties (code removed, code added) and behavioral equivalence.

## Walkthrough

### Step 1: File-derived rendering authority (R1, R2)

Show the cadence loop no longer references external cursors:

```bash
# Verify no last_tool_done_at in the cadence loop
! grep -n 'last_tool_done_at' teleclaude/adapters/ui/output_cadence.py
```

```bash
# Verify turn detection uses file-based scan with tool-result discrimination
grep -n '_is_user_tool_result_only_message\|_detect_turn_boundary\|_last_seen_user_ts' teleclaude/adapters/ui/output_cadence.py
```

### Step 2: Cadence-owned bookkeeping (R3)

```bash
# Verify cadence resets delivery bookkeeping directly
grep -n '_clear_output_message_id\|_set_char_offset' teleclaude/adapters/ui/output_cadence.py
```

### Step 3: Rendering mode switching (R4, R5)

```bash
# Verify origin/reflection mode branching exists in cadence
grep -n 'is_origin_mode\|last_input_origin\|ADAPTER_KEY' teleclaude/adapters/ui/output_cadence.py
```

```bash
# Verify _reflect_user_input is gone
! grep -n '_reflect_user_input' teleclaude/adapters/ui/output_cadence.py
```

```bash
# Verify broadcast_user_input is gone from _OutputMixin
! grep -n 'broadcast_user_input' teleclaude/core/adapter_client/_output.py
```

### Step 4: Lifecycle reduced to QoS (R6)

```bash
# Verify break_threaded_turn only drops QoS payloads
grep -A 15 'async def break_threaded_turn' teleclaude/core/adapter_client/_output.py
```

### Step 5: Signal-rendering separation (R7, R8)

```bash
# Verify coordinator does not set rendering cursors
! grep -n 'last_tool_done_at' teleclaude/core/agent_coordinator/_coordinator.py | grep -v 'def\|class\|#\|import'
```

```bash
# Verify no force_session_output_pull for terminal input in handle_user_prompt_submit
python3 -c "
import ast
from pathlib import Path
src = Path('teleclaude/core/agent_coordinator/_coordinator.py').read_text()
tree = ast.parse(src)
for node in ast.walk(tree):
    if isinstance(node, ast.AsyncFunctionDef) and node.name == 'handle_user_prompt_submit':
        body = ast.get_source_segment(src, node) or ''
        assert 'force_session_output_pull' not in body, 'Still present'
        print('PASS: force_session_output_pull removed from handle_user_prompt_submit')
        break
"
```

### Step 6: Superseded mechanisms removed (R9)

```bash
# Verify delivery_ts guard removed from send_threaded_output
python3 -c "
import ast
from pathlib import Path
src = Path('teleclaude/adapters/ui_adapter.py').read_text()
tree = ast.parse(src)
for node in ast.walk(tree):
    if isinstance(node, ast.AsyncFunctionDef) and node.name == 'send_threaded_output':
        params = [a.arg for a in node.args.args + node.args.kwonlyargs]
        assert 'delivery_ts' not in params, 'Still present'
        body = ast.get_source_segment(src, node) or ''
        assert 'last_delivered_at' not in body, 'Still present'
        print('PASS: delivery_ts guard removed')
        break
"
```

```bash
# Verify has_active_output_message not imported by cadence
! grep -n 'has_active_output_message' teleclaude/adapters/ui/output_cadence.py
```

### Step 7: Preserved behaviors (R10)

```bash
# Run the preserved behavior test suite — all must pass
python -m pytest tests/unit/adapters/ui/test_cadence_preserved_behaviors_spec.py -v --tb=short
```

### Step 8: Full spec verification

```bash
# Run all spec tests — no xfail markers should remain
python -m pytest tests/unit/adapters/ui/test_cadence_file_authority_spec.py tests/unit/adapters/ui/test_cadence_superseded_removal_spec.py tests/unit/adapters/ui/test_cadence_preserved_behaviors_spec.py -v --tb=short
```

## What the user observes

- All spec tests pass without xfail markers
- All preserved behavior tests continue to pass
- The cadence loop is simpler: reads file → detects turns → renders → sends
- No rendering state leaks from lifecycle or signal handlers
- break_threaded_turn is a 5-line method that drops QoS payloads
- handle_user_prompt_submit is shorter — no cursor manipulation, no force-pull
