# proficiency-to-expertise — Input

## Summary

Replace the flat `proficiency` field on PersonEntry with a structured `expertise` model that gives agents a richer signal about who they're working with.

## Schema Change

Current:
```yaml
proficiency: expert  # single flat level
```

New:
```yaml
expertise:
  teleclaude: novice                  # flat level — platform fluency, no sub-areas
  software-development:
    default: advanced
    backend: expert
    frontend: intermediate
    devops: advanced
    data: intermediate
    security: intermediate
  marketing:
    default: novice
    seo: novice
    social-media: novice
    analytics: novice
    advertising: novice
    branding: novice
  publishing:
    default: intermediate
    podcasting: novice
    video: novice
    articles: intermediate
    newsletters: novice
  creative:
    default: novice
    visual-design: novice
    copywriting: intermediate
    music: novice
    photography: novice
```

### Domain pillars

| Domain | What it is |
|--------|-----------|
| **teleclaude** | Platform fluency — flat level, no sub-areas |
| **software-development** | Technical domain knowledge |
| **marketing** | Promotion & strategy |
| **publishing** | Content production & distribution |
| **creative** | Craft & design |

### Design decisions

- No global default level. Unlisted domains = AI assumes intermediate or asks.
- teleclaude is a flat level (no sub-areas). All other domains have named sub-areas + a domain default.
- Levels: novice, intermediate, advanced, expert (same four as today).
- Freeform sub-area keys allowed — schema validates levels, not key names.
- The AI doesn't need domain detection or file-path mapping. It already knows what it's working on. The expertise blob is injected as text and the AI calibrates naturally.

## Injection Change

`receiver.py` renders the expertise block as human-readable text in the SessionStart hook instead of the single "Human in the loop: {name} ({level})" line. The AI reads the full expertise context and calibrates communication, autonomy, and explanation depth per domain naturally.

## Behavioral Templates

Per-level directive blocks injected alongside the expertise signal. These replace the static behavioral sections in CLAUDE.md that currently apply uniformly:

- Expert: "Act and report. Maximum density. Surface only genuine blockers."
- Novice: "Explain before acting. Plain language. Surface every decision point."

The Calibration principle stays as philosophical guidance. The injected templates are the operational implementation.

Sections in CLAUDE.md/AGENTS.md to refactor: Refined Tone Gradient, Evidence Before Assurance, Active Directive vs Conversational Input.

## Schema Implementation

### Pydantic model change (`config/schema.py:127-133`)

Replace:
```python
proficiency: Literal["novice", "intermediate", "advanced", "expert"] = "intermediate"
```

With a nested expertise model. The structure supports:
- Flat domain levels (e.g. `teleclaude: novice`) — just a string
- Structured domains with sub-areas (e.g. `software-development: {default: expert, frontend: intermediate}`) — dict with `default` key + freeform sub-area keys
- `extra="allow"` on PersonEntry already permits forward-compatible fields

Validation rules:
- All level values must be one of: novice, intermediate, advanced, expert
- Domain keys should include the known pillars but allow freeform
- Sub-area keys within domains are freeform — schema validates level values only

### API DTO change (`api_models.py:155-163`)

`PersonDTO.proficiency` → mirror the new expertise structure. Used in API responses.

### PersonInfo dataclass (`config_cli.py:79-90`)

`proficiency: str | None` → restructure for nested expertise data in JSON output.

## Config Wizard & CLI Changes

### TUI config wizard (`tui/views/config.py`)

Current state:
- `_PERSON_EDITABLE_FIELDS = ("email", "role", "username")` — proficiency is NOT editable in the wizard today
- Role uses enum cycling pattern (left/right arrows cycle through Literal values, line 610-628)
- Proficiency is only displayed as `[{proficiency}]` in person row (line 932)

Required changes:
- Add expertise to `_PERSON_EDITABLE_FIELDS`
- New UI pattern needed: expertise is a nested structure, not a single enum
- For each domain: present known sub-areas as enum-cycled fields (like role)
- Freeform entry for custom sub-areas
- Guided mode step for expertise during people setup (add to `_GUIDED_STEPS` tuple, line 94-102)
- Guidance text for expertise fields (via `GuidanceRegistry` in `config_components/guidance.py`)

### CLI commands (`config_cli.py`)

**Add person** (line 196-224):
- Replace `--proficiency` with expertise flags
- Support: `--expertise-teleclaude novice --expertise-software-development '{"default": "expert", "frontend": "intermediate"}'`
- Or simpler: `--expertise '{...}'` as JSON blob

**Edit person** (line 290-349):
- Support editing individual domain/sub-area levels
- e.g. `telec config people edit "Maurice" --expertise-software-development-frontend intermediate`
- Or dot-path: `telec config people edit "Maurice" --expertise software-development.frontend=intermediate`

**List people** (line 153-179):
- Serialize full expertise structure in JSON output (line 163)

### Config handlers (`config_handlers.py`)

- `save_global_config()` (line 269): must serialize the nested expertise model to YAML
- Note: blocked on `fix-telec-config-people-edit-fails-with-ruam` bug (ruamel can't serialize AutonomyLevel enum — same serialization layer)
- `_model_to_dict()` (line 264): Pydantic `model_dump()` should handle nested models naturally

## Injection Change Details

### Hook receiver (`hooks/receiver.py:235-278`)

Current injection (line 263-264):
```python
person_proficiency = getattr(person, "proficiency", "intermediate")
proficiency_line = f"Human in the loop: {person.name} ({person_proficiency})"
```

New injection renders the full expertise block as human-readable text. Example output:
```
Human in the loop: Maurice Faber
Expertise:
  teleclaude: expert
  software-development: expert (frontend: intermediate, devops: advanced)
  marketing: novice
```

The AI reads this naturally and calibrates per domain without code-path detection.

### Hook adapter (`hooks/adapters/claude.py:33-41`)

No change needed — adapter formats the context string as-is. The richer content flows through the same `additionalContext` JSON field.

## Test Changes

All existing tests must be updated:

| Test file | Lines | What changes |
|-----------|-------|-------------|
| `test_config_schema.py` | 405-421 | New schema validation tests for nested expertise model |
| `test_hooks_receiver_memory.py` | 100-170 | Injection tests: verify richer expertise block rendering |
| `test_config_cli.py` | 357-411 | CLI add/edit/list tests for new expertise flags |

## Migration

- `proficiency` field stays supported during transition — if present, maps to a single-domain expertise entry
- `telec config people edit` updated for new schema (blocked on fix-telec-config-people-edit-fails-with-ruam bug)
- Config wizard gets expertise section as a new guided step
- Existing person configs without expertise: fall back to intermediate (same as today's default)

## Touchpoint Summary

| Component | File | Lines | Change needed |
|-----------|------|-------|--------------|
| Schema | `config/schema.py` | 127-133 | Replace proficiency with expertise model |
| API DTO | `api_models.py` | 155-163 | Mirror new structure |
| Injection | `hooks/receiver.py` | 243-264 | Render rich expertise block |
| CLI add | `config_cli.py` | 196-224 | New expertise flags |
| CLI edit | `config_cli.py` | 290-349 | Dot-path expertise editing |
| CLI list | `config_cli.py` | 153-179 | Serialize expertise in output |
| PersonInfo | `config_cli.py` | 79-90 | Restructure dataclass |
| TUI display | `tui/views/config.py` | 932 | Render expertise summary |
| TUI edit | `tui/views/config.py` | 610-628 | New nested editing pattern |
| TUI wizard | `tui/views/config.py` | 94-102 | Add expertise guided step |
| Guidance | `tui/config_components/guidance.py` | — | Add expertise field guidance |
| Config save | `config_handlers.py` | 269 | Serialize nested model |
| Schema tests | `test_config_schema.py` | 405-421 | New validation tests |
| Injection tests | `test_hooks_receiver_memory.py` | 100-170 | Rich block tests |
| CLI tests | `test_config_cli.py` | 357-411 | New flag tests |
| Demo | `demos/person-proficiency-level/` | — | Update or replace demo |

## Out of Scope (future ideas)

- Session-scoped overrides (--calibration "frontend:novice")
- Per-person behavioral preferences (style, risk tolerance, commit style)
- Adaptive calibration / Memory API observations
- Team-aware calibration (audience-based artifact tuning)
- Automatic proficiency progression suggestions

## Origin

Brainstormed in peer discussion session 3845035c between two Claude agents. Key insight from peer: the injection templates should REPLACE static behavioral sections, not bolt on alongside them — migration is Phase 1, not cleanup.
