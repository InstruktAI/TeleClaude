# proficiency-to-expertise-tui — Input

## Summary

Add expertise editing to the TUI config wizard. Replace the flat proficiency display with a structured expertise editor.

## TUI Changes

### Config wizard (`tui/views/config.py`)

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

### Display

- Person row should show a summary of expertise domains instead of single `[{proficiency}]`
- Expanded view shows full domain/sub-area tree

## Touchpoints

| Component | File | Lines | Change needed |
|-----------|------|-------|--------------|
| TUI display | `tui/views/config.py` | 932 | Render expertise summary |
| TUI edit | `tui/views/config.py` | 610-628 | New nested editing pattern |
| TUI wizard | `tui/views/config.py` | 94-102 | Add expertise guided step |
| Guidance | `tui/config_components/guidance.py` | — | Add expertise field guidance |

## Dependency

Requires `proficiency-to-expertise-schema` (the Pydantic model) to be complete first.
