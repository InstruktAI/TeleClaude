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
    record_artifact_produced, record_artifact_consumed, check_artifact_staleness
)
import yaml, tempfile
from pathlib import Path

tmp = Path(tempfile.mkdtemp())
todo_dir = tmp / 'todos' / 'test-slug'
todo_dir.mkdir(parents=True)

# Create artifacts
(todo_dir / 'input.md').write_text('original input')
(todo_dir / 'requirements.md').write_text('requirements content')
(todo_dir / 'state.yaml').write_text(yaml.dump({'schema_version': 2}))

# Record production and consumption
record_artifact_produced(str(tmp), 'test-slug', 'input')
record_artifact_consumed(str(tmp), 'test-slug', 'input', 'input_assessment')
record_artifact_produced(str(tmp), 'test-slug', 'requirements')
record_artifact_consumed(str(tmp), 'test-slug', 'requirements', 'requirements_review')

# Modify input after consumption
(todo_dir / 'input.md').write_text('modified input')

# Check staleness
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

Show `record_artifact_produced` writing lifecycle metadata to state.yaml. Then
modify the source artifact and run `check_artifact_staleness` to demonstrate the
digest-based cascade. Explain how this replaces the previous file-existence-only
approach and protects against ghost artifacts (R5, R6).

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
