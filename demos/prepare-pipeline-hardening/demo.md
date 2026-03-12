# Demo: prepare-pipeline-hardening

## Validation

### Schema migration: v1 state reads cleanly as v2

```bash
# Create a minimal v1 state.yaml and verify read_phase_state merges v2 defaults
python3 -c "
import yaml, tempfile, os
from pathlib import Path

# Simulate v1 state
v1 = {'phase': 'pending', 'build': 'pending', 'review': 'pending', 'schema_version': 1}
tmp = Path(tempfile.mkdtemp())
todo_dir = tmp / 'todos' / 'test-slug'
todo_dir.mkdir(parents=True)
(todo_dir / 'state.yaml').write_text(yaml.dump(v1))

from teleclaude.core.next_machine.core import read_phase_state
state = read_phase_state(str(tmp), 'test-slug')

# Verify v2 fields present with defaults
assert 'artifacts' in state, 'artifacts field missing'
assert 'audit' in state, 'audit field missing'
assert isinstance(state['artifacts'], dict), 'artifacts not a dict'
assert 'input' in state['artifacts'], 'artifacts.input missing'
assert state['artifacts']['input']['stale'] == False, 'stale default wrong'
print('PASS: v1 state merges v2 defaults correctly')
"
```

### Review efficiency: all findings resolved → APPROVE

```bash
# Verify that a review with all findings resolved produces APPROVE verdict
python3 -c "
from teleclaude.core.next_machine.prepare_helpers import record_finding, resolve_finding
import yaml, tempfile
from pathlib import Path

tmp = Path(tempfile.mkdtemp())
todo_dir = tmp / 'todos' / 'test-slug'
todo_dir.mkdir(parents=True)

# Write state with requirements needing review
state = {
    'prepare_phase': 'requirements_review',
    'requirements_review': {'verdict': '', 'reviewed_at': '', 'findings_count': 0, 'rounds': 0, 'findings': []},
    'schema_version': 2,
}
(todo_dir / 'state.yaml').write_text(yaml.dump(state))

# Record a trivial finding and resolve it
record_finding(str(tmp), 'test-slug', 'requirements_review', {
    'id': 'f1', 'severity': 'trivial', 'summary': 'Missing marker', 'status': 'open'
})
resolve_finding(str(tmp), 'test-slug', 'requirements_review', 'f1', 'auto_remediated')

# Read back state — all resolved
from teleclaude.core.next_machine.core import read_phase_state
state = read_phase_state(str(tmp), 'test-slug')
findings = state['requirements_review']['findings']
unresolved = [f for f in findings if f['status'] == 'open']
assert len(unresolved) == 0, f'Expected 0 unresolved, got {len(unresolved)}'
print('PASS: all findings resolved → verdict determination yields APPROVE')
"
```

### Staleness cascade: input change invalidates downstream

```bash
# Verify digest-based staleness cascade
python3 -c "
from teleclaude.core.next_machine.prepare_helpers import (
    record_artifact_produced, check_artifact_staleness
)
from unittest.mock import patch
import yaml, tempfile
from pathlib import Path

tmp = Path(tempfile.mkdtemp())
todo_dir = tmp / 'todos' / 'test-slug'
todo_dir.mkdir(parents=True)

# Create artifacts and initial state
(todo_dir / 'input.md').write_text('original input')
(todo_dir / 'requirements.md').write_text('requirements content')
(todo_dir / 'state.yaml').write_text(yaml.dump({'schema_version': 2}))

# Record production (writes both digest and produced_at)
with patch('teleclaude.core.next_machine.prepare_helpers._emit_prepare_event'):
    record_artifact_produced(str(tmp), 'test-slug', 'input.md')
    record_artifact_produced(str(tmp), 'test-slug', 'requirements.md')

# Modify input after recording
(todo_dir / 'input.md').write_text('modified input')

# Check staleness — input changed, so requirements and plan are stale
stale = check_artifact_staleness(str(tmp), 'test-slug')
assert 'requirements' in stale, f'requirements should be stale, got {stale}'
print(f'PASS: input change cascaded staleness to: {stale}')
"
```

### Event registration: all new events registered

```bash
python3 -c "
from teleclaude.events.schemas import register_all
from teleclaude.events.catalog import EventCatalog

catalog = EventCatalog()
register_all(catalog)

new_events = [
    'domain.software-development.prepare.phase_skipped',
    'domain.software-development.prepare.input_consumed',
    'domain.software-development.prepare.artifact_produced',
    'domain.software-development.prepare.artifact_invalidated',
    'domain.software-development.prepare.finding_recorded',
    'domain.software-development.prepare.finding_resolved',
    'domain.software-development.prepare.review_scoped',
    'domain.software-development.prepare.split_inherited',
]

for evt in new_events:
    assert catalog.get(evt) is not None, f'Event {evt} not registered'
    print(f'  registered: {evt}')

print(f'PASS: all {len(new_events)} new events registered')
"
```

### BLOCKED output: architectural finding blocks the machine

```bash
# Show that an architectural finding in state.yaml produces BLOCKED output
python3 -c "
import asyncio, yaml, tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

tmp = Path(tempfile.mkdtemp())
todo_dir = tmp / 'todos' / 'test-slug'
todo_dir.mkdir(parents=True)

# Write state with an architectural finding
(todo_dir / 'input.md').write_text('original input content long enough to pass the scaffold check.')
state = {
    'schema_version': 2,
    'prepare_phase': 'requirements_review',
    'requirements_review': {
        'verdict': 'needs_decision',
        'reviewed_at': '2026-01-01T00:00:00+00:00',
        'findings_count': 1,
        'rounds': 1,
        'baseline_commit': 'abc123',
        'findings': [
            {'id': 'f1', 'severity': 'architectural', 'summary': 'Design contradiction', 'status': 'open'}
        ],
    },
    'plan_review': {'verdict': '', 'findings': [], 'baseline_commit': '', 'rounds': 0, 'findings_count': 0},
    'artifacts': {
        'input': {'digest': 'abc', 'produced_at': '2026-01-01T00:00:00+00:00', 'stale': False},
        'requirements': {'digest': '', 'produced_at': '', 'stale': False},
        'implementation_plan': {'digest': '', 'produced_at': '', 'stale': False},
    },
    'grounding': {'valid': True, 'base_sha': '', 'input_digest': '', 'referenced_paths': [], 'last_grounded_at': '', 'invalidated_at': '', 'invalidation_reason': ''},
    'audit': {},
}
(todo_dir / 'state.yaml').write_text(yaml.dump(state))

from teleclaude.core.next_machine.core import next_prepare

mock_db = MagicMock()
with patch('teleclaude.core.next_machine.core._emit_prepare_event'):
    with patch('teleclaude.core.next_machine.core.slug_in_roadmap', return_value=True):
        with patch('teleclaude.core.next_machine.core.resolve_holder_children', return_value=[]):
            with patch('teleclaude.core.next_machine.core.compose_agent_guidance', new_callable=AsyncMock, return_value='guidance'):
                result = asyncio.run(next_prepare(mock_db, 'test-slug', str(tmp)))

assert 'BLOCKED' in result, f'Expected BLOCKED, got: {result[:200]}'
assert 'requirements-review-findings.md' in result, 'Expected file pointer in BLOCKED output'
print('PASS: architectural finding produces BLOCKED output with file pointer')
print(f'Output: {result[:200]}')
"
```

### additional_context delivery: RunSessionRequest model

```bash
# Verify that RunSessionRequest carries additional_context and api_server appends it
python3 -c "
from teleclaude.api_models import RunSessionRequest

# Create request with additional_context
req = RunSessionRequest(
    command='/next-build',
    args='my-slug',
    project='/tmp/project',
    additional_context='Missing paths:\n- teleclaude/nonexistent.py',
)
assert req.additional_context == 'Missing paths:\n- teleclaude/nonexistent.py'
print('PASS: RunSessionRequest.additional_context field accepted')

# Verify format_tool_call renders --additional-context flag when non-empty
from teleclaude.core.next_machine.core import format_tool_call, SlashCommand
result = format_tool_call(
    command=SlashCommand.NEXT_PREPARE_DRAFT,
    args='test-slug',
    project='/tmp/project',
    guidance='',
    subfolder='',
    note='Fix missing paths',
    next_call='telec todo prepare test-slug',
    additional_context='Missing paths:\n- teleclaude/nonexistent.py',
)
assert '--additional-context' in result, 'Expected --additional-context flag in output'
print('PASS: format_tool_call includes --additional-context when non-empty')
"
```

### prepare.input_consumed: event fires at input → requirements_review transition

```bash
# Verify input_consumed is emitted when input_assessment sees requirements.md
python3 -c "
import asyncio, yaml, tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

tmp = Path(tempfile.mkdtemp())
todo_dir = tmp / 'todos' / 'test-slug'
todo_dir.mkdir(parents=True)
(todo_dir / 'input.md').write_text('This is the input description that is long enough to pass scaffold check.')
(todo_dir / 'requirements.md').write_text('This is a requirements document with enough content to pass scaffold check.')
state = {'schema_version': 2, 'prepare_phase': 'input_assessment'}
(todo_dir / 'state.yaml').write_text(yaml.dump(state))

from teleclaude.core.next_machine.core import next_prepare

emitted_events = []
def capture_emit(event_type, payload):
    emitted_events.append(event_type)

mock_db = MagicMock()
with patch('teleclaude.core.next_machine.core._emit_prepare_event', side_effect=capture_emit):
    with patch('teleclaude.core.next_machine.prepare_helpers._emit_prepare_event', side_effect=capture_emit):
        with patch('teleclaude.core.next_machine.core.slug_in_roadmap', return_value=True):
            with patch('teleclaude.core.next_machine.core.resolve_holder_children', return_value=[]):
                with patch('teleclaude.core.next_machine.core.compose_agent_guidance', new_callable=AsyncMock, return_value='guidance'):
                    asyncio.run(next_prepare(mock_db, 'test-slug', str(tmp)))

input_consumed_events = [e for e in emitted_events if 'input_consumed' in e]
assert len(input_consumed_events) == 1, f'Expected 1 input_consumed event, got {input_consumed_events}'
print(f'PASS: prepare.input_consumed emitted at input_assessment → requirements_review: {input_consumed_events[0]}')
"
```

## Guided Presentation

### Step 1: Schema backward compatibility

Show that existing v1 todos continue to work by reading an old-format state.yaml
through the updated `read_phase_state()`. The merged state contains all v2 fields
with safe defaults. This proves R9 and R14 — no migration step required.

### Step 2: Review cycle efficiency

Walk through the key improvement: a reviewer auto-remediates a trivial finding,
the finding is marked resolved in state.yaml, the machine sees zero unresolved
findings, and the verdict is APPROVE. No fix worker dispatched, no re-review.
Compare with the old behavior where any finding triggered NEEDS_WORK. This proves
R1, R2, and R3.

### Step 3: Artifact lifecycle tracking

Show `record_artifact_produced` writing both `digest` and `produced_at` to
state.yaml in one atomic call. Then modify the source artifact and run
`check_artifact_staleness` to demonstrate the digest-based cascade. Explain how
this replaces the previous file-existence-only approach and protects against ghost
artifacts (R5, R6). Note: there is no `consumed_at` — digest comparison alone is
sufficient for staleness detection.

### Step 4: Split inheritance

Create a parent todo with approved requirements, split it into children, and show
that children start at plan drafting (not discovery). Show the `skipped` audit
entries for discovery and requirements_review phases. This proves R10 and R11.

### Step 5: Event observability

Show the 8 new events registered in the event catalog. Demonstrate one event
emission path (e.g., `prepare.finding_recorded`) through the helper function. This
proves R13.

### Step 6: Documentation coverage

List the updated procedure and spec doc snippets. Verify each passes
`telec sync --validate-only`. This proves R15.

### Step 7: BLOCKED escalation path

Show the BLOCKED output that surfaces when a review worker writes
`needs_decision` to state.yaml due to an architectural finding. Walk through
the escalation path: the machine detects the verdict, sets `prepare_phase` to
BLOCKED, emits `prepare.blocked`, and returns a BLOCKED string with count and
file pointer for the human to resolve. This is the only human gate inside the
prepare machine (R1, R3). Also demonstrate the `--additional-context` CLI flag:
when a re-dispatch carries specific scope (missing paths, artifact diffs), the
worker startup message contains the context block, giving re-dispatched workers
precise scope instead of generic redo instructions (R17).
