# Requirements: proficiency-to-expertise

## Goal

Replace the flat `proficiency` field on PersonEntry with a structured `expertise`
model that gives agents a richer signal about who they're working with — per-domain
and per-sub-area proficiency levels instead of a single global level.

## In scope

1. New Pydantic model for expertise with support for:
   - Flat domain levels (e.g. `teleclaude: novice`) — string value
   - Structured domains with sub-areas (e.g. `software-development: {default: expert, frontend: intermediate}`) — dict with `default` key + freeform sub-area keys
2. Replace `proficiency` field on `PersonEntry` (`config/schema.py:133`) with `expertise`
3. Mirror the change on `PersonDTO` (`api_models.py:164`)
4. Update `PersonInfo` dataclass (`config_cli.py:80-90`) to carry expertise data
5. Update CLI commands:
   - `_people_add` (`config_cli.py:196-226`): accept `--expertise` JSON blob
   - `_people_edit` (`config_cli.py:290-349`): accept `--expertise` for full replace or dot-path edits
   - `_people_list` (`config_cli.py:153-179`): serialize expertise in JSON output
6. Update hook injection (`hooks/receiver.py:243-264`): render expertise block instead of flat proficiency line
7. Update TUI display (`tui/views/config.py:932`): show expertise summary instead of `[{proficiency}]`
8. Update all existing tests that reference `proficiency`
9. Backward-compatible migration: accept old `proficiency` field, map to `software-development.default`

## Out of scope

- TUI editing/wizard for expertise (future todo — display-only for now) [inferred]
- Behavioral template injection (replacing CLAUDE.md static sections) — separate concern
- Session-scoped overrides, adaptive calibration, per-person behavioral preferences
- Config wizard guided step for expertise (future — CLI-first)

## Success Criteria

- [ ] `PersonEntry(expertise={"teleclaude": "novice", "software-development": {"default": "expert", "frontend": "intermediate"}})` validates
- [ ] `PersonEntry(proficiency="expert")` still works (migration: maps to `software-development.default`)
- [ ] `PersonEntry()` with no expertise/proficiency defaults to empty expertise (AI assumes intermediate per Calibration principle)
- [ ] Invalid level values (e.g. "guru") raise ValidationError
- [ ] Freeform domain and sub-area keys are accepted
- [ ] `PersonDTO` mirrors the expertise structure
- [ ] CLI `telec config people add --name X --email Y --expertise '{"teleclaude": "novice"}'` works
- [ ] CLI `telec config people edit X --expertise '{"software-development": {"frontend": "advanced"}}'` merges into existing expertise
- [ ] CLI `telec config people list --json` includes full expertise structure
- [ ] Hook injection renders human-readable expertise block (e.g. `Human in the loop: Maurice Faber\nExpertise:\n  teleclaude: expert\n  software-development: expert (frontend: intermediate)`)
- [ ] TUI person row shows expertise summary
- [ ] All existing proficiency tests updated and passing
- [ ] `make test` passes, `make lint` passes

## Constraints

- Backward compatibility: existing configs with `proficiency` must continue to work
- No new third-party dependencies
- `extra="allow"` on PersonEntry already permits forward-compatible fields

## Risks

- Config serialization: ruamel YAML serialization of nested Pydantic models may need attention (input.md mentioned a related bug — verify current behavior)
