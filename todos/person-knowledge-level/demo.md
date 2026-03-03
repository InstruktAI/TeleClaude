# Demo: person-knowledge-level

## Validation

```bash
# Schema validates valid knowledge levels
python3 -c "
from teleclaude.config.schema import PersonEntry
p = PersonEntry(name='Test', email='test@test.com', knowledge='expert')
assert p.knowledge == 'expert'
print('Schema validation: PASS')
"
```

```bash
# Schema rejects invalid knowledge levels
python3 -c "
from teleclaude.config.schema import PersonEntry
try:
    PersonEntry(name='Test', email='test@test.com', knowledge='guru')
    print('Schema validation: FAIL — should have raised')
    exit(1)
except Exception:
    print('Schema rejection: PASS')
"
```

```bash
# Default knowledge level is 'intermediate'
python3 -c "
from teleclaude.config.schema import PersonEntry
p = PersonEntry(name='Test', email='test@test.com')
assert p.knowledge == 'intermediate'
print('Default knowledge: PASS')
"
```

```bash
# CLI: add person with knowledge level
telec config people add --name DemoUser --email demo@test.com --knowledge expert --no-invite --json
```

```bash
# CLI: list shows knowledge
telec config people list --json | python3 -c "import sys,json; data=json.load(sys.stdin); print([p for p in data if p['name']=='DemoUser'])"
```

```bash
# CLI: edit knowledge level
telec config people edit DemoUser --knowledge novice --json
```

```bash
# Cleanup
telec config people remove DemoUser --json
```

## Guided Presentation

1. **Schema field** — Show that `PersonEntry` now accepts `knowledge` with four valid
   levels and defaults to `intermediate`. Invalid values are rejected by Pydantic.

2. **CLI integration** — Add a demo person with `--knowledge expert`, verify it appears
   in `people list --json` output, then edit it to `novice` and verify the change.

3. **Session injection** — Start a session where the human has `knowledge: expert` in
   config. Tail the session's first message to show the injected
   `Human in the loop: {name} (expert)` line in the additional context.

4. **TUI wizard** — Open `telec config wizard`, navigate to the People tab, and observe
   the knowledge level displayed next to each person's name and role.

5. **Cleanup** — Remove the demo person.
