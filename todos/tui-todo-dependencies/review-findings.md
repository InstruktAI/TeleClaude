# Review Findings: tui-todo-dependencies

## Round 2

### Critical

(none)

### Important

(none)

### Suggestions

(none)

All findings from Round 1 have been resolved.

---

## Round 1 — Resolved

### Fixes Applied

#### 1. GroupSeparator width calculation (Important)

**Issue:** Width calculation off by 2 — used constant `5` instead of `7`

**Fix:** Changed `width - col - 5 - len(self._label)` to `width - col - 7 - len(self._label)` in `group_separator.py:44`

**Commit:** `6a089663` — fix(tui): correct GroupSeparator width calculation off-by-2

**Verification:** Lint pass | Hooks pass

#### 2. Module docstring alignment (Suggestion)

**Issue:** Module docstring only mentioned "closing separator" role

**Fix:** Updated module docstring to "Separator line widget for tree views: closing lines and group sub-headers."

**Commit:** `dcc6e544` — docs(tui): update GroupSeparator module docstring to reflect dual purpose

**Verification:** Lint pass | Hooks pass

---

## Requirements Trace

| Requirement                               | Status | Evidence                                                     |
| ----------------------------------------- | ------ | ------------------------------------------------------------ |
| API response includes `after` and `group` | pass   | `api_models.py:193-194`, `api_server.py:1143-1144,1176-1177` |
| Dimmed dependency suffix on todo rows     | pass   | `todo_row.py:199-201`                                        |
| Group sub-headers in Preparation view     | pass   | `preparation.py:162-169`                                     |
| Display matches `telec roadmap` info      | pass   | Both dependency arrows and group labels present              |
| No regressions in existing tests          | pass   | Build gates confirm tests pass                               |

## Implementation Quality

- Field additions follow existing dataclass/DTO patterns consistently across all 6 layers
- Safe defaults (`default_factory=list`, `None`) ensure backward compatibility with cached data
- Defensive `getattr` usage in `PreparationView` matches existing pattern for other fields
- `from_dict()` deserialization handles missing fields gracefully
- `to_dict()` via `asdict()` automatically picks up new fields — no manual wiring needed
- Group tracking logic in `PreparationView` correctly handles transitions between groups and ungrouped items
- `GroupSeparator` not added to `_nav_items` — correct, separators should not be keyboard-navigable
- Width calculation verified correct: `col + 1 + 5 + len(label) + 1 + remaining = width` when `remaining = width - col - 7 - len(label)`

## Verdict: APPROVE
