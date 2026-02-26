# Demo: harmonize-agent-notifications

## Medium

CLI + daemon logs. Notifications are control-plane events observed via tmux injection
and daemon log output.

## Validation

```bash
# 1. Verify canonical vocabulary includes agent_notification
python -c "from teleclaude.core.activity_contract import HOOK_TO_CANONICAL; assert 'notification' in HOOK_TO_CANONICAL, 'notification not in HOOK_TO_CANONICAL'; print('PASS: notification mapped to', HOOK_TO_CANONICAL['notification'])"
```

```bash
# 2. Verify tag stripping works on sample input
python -c "
from teleclaude.core.agent_coordinator import strip_signaling_tags
raw = '<task-notification>Session abc needs input</task-notification>'
clean = strip_signaling_tags(raw)
assert '<' not in clean, f'Tags not stripped: {clean}'
print(f'PASS: \"{raw}\" → \"{clean}\"')
"
```

```bash
# 3. Verify AgentActivityEvent has message field
python -c "
from teleclaude.core.events import AgentActivityEvent
import dataclasses
fields = {f.name for f in dataclasses.fields(AgentActivityEvent)}
assert 'message' in fields, f'message not in AgentActivityEvent fields: {fields}'
print('PASS: AgentActivityEvent has message field')
"
```

```bash
# 4. Verify CanonicalActivityEvent has message field
python -c "
from teleclaude.core.activity_contract import CanonicalActivityEvent
import dataclasses
fields = {f.name for f in dataclasses.fields(CanonicalActivityEvent)}
assert 'message' in fields, f'message not in CanonicalActivityEvent fields: {fields}'
print('PASS: CanonicalActivityEvent has message field')
"
```

## Guided Presentation

### Step 1: Vocabulary expansion

Show that the canonical activity contract now recognizes notification hooks.

**Observe:** `HOOK_TO_CANONICAL` contains `"notification" → "agent_notification"`.
**Why it matters:** This is the foundation — without the mapping, notification hooks
would continue to be silently skipped by `serialize_activity_event()`.

### Step 2: Tag stripping

Demonstrate that internal XML signaling tags are removed from notification text.

**Do:** Run the tag stripping validation script above.
**Observe:** Input `<task-notification>Session abc needs input</task-notification>`
produces clean output `Session abc needs input`.
**Why it matters:** This prevents raw XML from leaking into tmux panes and remote
notification forwarding.

### Step 3: Event bus emission

Show that notification hooks now produce canonical events on the event bus.

**Do:** Start a TeleClaude session, trigger a notification (e.g., permission request
from a Claude Code subagent), and inspect daemon logs.
**Observe:** Log entry showing `agent_notification` canonical event emitted with a
clean `message` field.
**Why it matters:** Web and TUI adapters can now consume notification state through
the standard event bus instead of relying on tmux injection.

### Step 4: Existing paths preserved

Confirm that the tmux injection and remote forwarding paths still work.

**Do:** Verify that listener sessions still receive notification messages in their
tmux panes, and that cross-computer forwarding delivers the cleaned message.
**Observe:** Same notification delivery behavior, but with clean message text.
**Why it matters:** Backward compatibility — no existing notification flows break.
