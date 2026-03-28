# Demo: orchestrator-heartbeat-timestamp-monitoring

## Validation

```bash
# Verify timestamp comparison rule is present in orchestration output
python3 -c "
from teleclaude.core.next_machine.output_formatting import ToolCallRequest, format_tool_call
output = format_tool_call(ToolCallRequest(
    command='next-build', args='demo-slug', project='/repo',
    guidance='guidance', subfolder='trees/demo-slug',
))
assert 'last_activity' in output, 'Missing last_activity field reference'
assert 'last_output_summary_at' in output, 'Missing last_output_summary_at field reference'
assert 'IF YOU SELECTED CODEX' not in output, 'Codex-specific section still present'
assert 'IF YOU SELECTED CLAUDE' not in output, 'Claude-specific section still present'
assert 'observation heartbeat' not in output.lower(), 'Two-heartbeat protocol still present'
print('PASS: Timestamp comparison rule present, agent-specific sections removed')
"
```

```bash
# Verify notification wording does not imply completion
python3 -c "
import asyncio
from unittest.mock import patch, AsyncMock
from teleclaude.core.session_listeners import notify_stop

with patch('teleclaude.core.session_listeners.get_listeners', new=AsyncMock(return_value=[])):
    # We can't easily test the full notify path without DB, but we can test the message construction
    pass
# Instead verify the source directly
import inspect
source = inspect.getsource(notify_stop)
assert 'finished its turn' not in source, 'Old completion-implying wording still present'
print('PASS: Notification wording updated')
"
```

```bash
# Verify all tests pass
cd /Users/Morriz/Workspace/InstruktAI/TeleClaude/trees/orchestrator-heartbeat-timestamp-monitoring
python3 -m pytest tests/unit/core/next_machine/test_output_formatting.py tests/unit/core/next_machine/test_work.py tests/unit/core/next_machine/test_build_gates.py -q
```

## Guided Presentation

### Step 1: The problem — agent-specific branching

Show the old STEP 3 section in `output_formatting.py` that contained
Codex-specific two-heartbeat protocol and Claude/Gemini notification-trust
model. These were two different heuristics for the same question: "is the
worker still active?"

### Step 2: The solution — deterministic timestamp comparison

Show the new STEP 3 section. All heartbeat triggers (notification, timer,
manual check) now run the same assessment: compare `last_activity` to
`last_output_summary_at` from `telec sessions list`. If activity is newer
than the last summarized output, the worker is active. If equal, the worker
is idle/settled.

### Step 3: Notification wording alignment

Show the updated `notify_stop()` message. It no longer says "finished its
turn" — instead it frames the event as a heartbeat trigger that prompts
assessment via the timestamp rule.

### Step 4: Test coverage

Run the test suite to demonstrate all behavioral assertions pass. Show that
the new tests verify the timestamp rule presence and agent-conditional
absence without prose-locking on exact instruction wording.
