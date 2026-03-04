# Demo: person-proficiency-level

## Validation

```bash
# Schema validates valid proficiency levels
python3 -c "
from teleclaude.config.schema import PersonEntry
p = PersonEntry(name='Test', email='test@test.com', proficiency='expert')
assert p.proficiency == 'expert'
print('Schema validation: PASS')
"
```

```bash
# Schema rejects invalid proficiency levels
python3 -c "
from teleclaude.config.schema import PersonEntry
try:
    PersonEntry(name='Test', email='test@test.com', proficiency='guru')
    print('Schema validation: FAIL — should have raised')
    exit(1)
except Exception:
    print('Schema rejection: PASS')
"
```

```bash
# Default proficiency level is 'intermediate'
python3 -c "
from teleclaude.config.schema import PersonEntry
p = PersonEntry(name='Test', email='test@test.com')
assert p.proficiency == 'intermediate'
print('Default proficiency: PASS')
"
```

```bash
# CLI: add person with proficiency level
telec config people add --name DemoUser --email demo@test.com --proficiency expert --no-invite --json
```

```bash
# CLI: list shows proficiency
telec config people list --json | python3 -c "import sys,json; data=json.load(sys.stdin); print([p for p in data if p['name']=='DemoUser'])"
```

```bash
# CLI: edit proficiency level
telec config people edit DemoUser --proficiency novice --json
```

```bash
# Cleanup
telec config people remove DemoUser --json
```

## Guided Presentation

1. **Schema field** — Show that `PersonEntry` now accepts `proficiency` with four valid
   levels and defaults to `intermediate`. Invalid values are rejected by Pydantic.

2. **CLI integration** — Add a demo person with `--proficiency expert`, verify it appears
   in `people list --json` output, then edit it to `novice` and verify the change.

3. **Session injection** — Start a session where the human has `proficiency: expert` in
   config. Tail the session's first message to show the injected
   `Human in the loop: {name} (expert)` line in the additional context.

4. **TUI wizard** — Open `telec config wizard`, navigate to the People tab, and observe
   the proficiency level displayed next to each person's name and role.

5. **Cleanup** — Remove the demo person.
