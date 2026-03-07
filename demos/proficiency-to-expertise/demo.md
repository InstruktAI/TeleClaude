# Demo: proficiency-to-expertise

## Validation

### Schema: flat domain expertise

```bash
python -c "
from teleclaude.config.schema import PersonEntry
e = PersonEntry(name='Alice', email='alice@example.com', expertise={'teleclaude': 'expert', 'marketing': 'novice'})
assert e.expertise['teleclaude'] == 'expert'
assert e.expertise['marketing'] == 'novice'
assert e.proficiency is None
print('PASS: flat domain expertise validates correctly')
"
```

### Schema: structured domain with sub-areas

```bash
python -c "
from teleclaude.config.schema import PersonEntry
e = PersonEntry(
    name='Alice',
    email='alice@example.com',
    expertise={
        'software-development': {'default': 'advanced', 'frontend': 'intermediate'},
        'teleclaude': 'expert',
    }
)
assert e.expertise['software-development']['default'] == 'advanced'
assert e.expertise['software-development']['frontend'] == 'intermediate'
print('PASS: structured domain expertise validates correctly')
"
```

### Schema: invalid level rejected

```bash
python -c "
from teleclaude.config.schema import PersonEntry
from pydantic import ValidationError
try:
    PersonEntry(name='Alice', email='alice@example.com', expertise={'teleclaude': 'guru'})
    print('FAIL: should have raised ValidationError')
    exit(1)
except ValidationError:
    print('PASS: invalid level rejected')
"
```

### Schema: backward compat — old proficiency field still works

```bash
python -c "
from teleclaude.config.schema import PersonEntry
e = PersonEntry(name='Bob', email='bob@example.com', proficiency='expert')
assert e.proficiency == 'expert'
assert e.expertise is None
print('PASS: legacy proficiency field still accepted')
"
```

### Injection: expertise block rendering

```bash
python -c "
from teleclaude.hooks.receiver import _render_person_header
from teleclaude.config.schema import PersonEntry

# Structured domain
p = PersonEntry(
    name='Maurice',
    email='mo@example.com',
    expertise={
        'teleclaude': 'expert',
        'software-development': {'default': 'advanced', 'frontend': 'intermediate'},
        'marketing': 'novice',
    }
)
out = _render_person_header(p)
assert out.startswith('Human in the loop: Maurice')
assert 'Expertise:' in out
assert 'teleclaude: expert' in out
assert 'software-development: advanced (frontend: intermediate)' in out
assert 'marketing: novice' in out
print('PASS: expertise block renders correctly')
print(out)
"
```

### Injection: backward compat — proficiency-only renders flat line

```bash
python -c "
from teleclaude.hooks.receiver import _render_person_header
from teleclaude.config.schema import PersonEntry

p = PersonEntry(name='Bob', email='bob@example.com', proficiency='expert')
out = _render_person_header(p)
assert out == 'Human in the loop: Bob (expert)'
print('PASS: proficiency-only renders flat line')
print(out)
"
```

### CLI: add person with expertise JSON blob

```bash
python -c "
import json, tempfile, os, sys
from pathlib import Path
from unittest.mock import patch

tmp = Path(tempfile.mkdtemp())
cfg_path = tmp / 'teleclaude.yml'
people_dir = tmp / 'people'
people_dir.mkdir()
cfg_path.write_text('people: []\n')

with (
    patch('teleclaude.cli.config_handlers._GLOBAL_CONFIG_PATH', cfg_path),
    patch('teleclaude.cli.config_handlers._PEOPLE_DIR', people_dir),
):
    from teleclaude.cli.config_cli import handle_config_cli
    from teleclaude.cli.config_handlers import get_global_config
    handle_config_cli([
        'people', 'add',
        '--name', 'Expert',
        '--email', 'expert@example.com',
        '--expertise', json.dumps({'teleclaude': 'expert', 'software-development': {'default': 'advanced'}}),
        '--json',
    ])
    config = get_global_config()
    p = next(x for x in config.people if x.name == 'Expert')
    assert p.expertise['teleclaude'] == 'expert'
    print('PASS: CLI add with --expertise works')
    print('Expertise:', p.expertise)
"
```

## Guided Presentation

Present the expertise signal changes to the user. Walk through:

1. Show the old schema (`proficiency: expert` flat field) vs new (`expertise:` structured block).
2. Demonstrate adding a person with full expertise YAML.
3. Show the rendered injection output that agents now receive in `Human in the loop` block.
4. Confirm backward compat: old `proficiency` field still loads without error.
