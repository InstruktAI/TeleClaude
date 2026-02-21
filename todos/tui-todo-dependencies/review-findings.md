# Review Findings: tui-todo-dependencies

## Critical

(none)

## Important

### 1. GroupSeparator labeled-line width calculation off by 2

**File:** `teleclaude/cli/tui/widgets/group_separator.py:44`

The `remaining` calculation for labeled separators undercounts by 2, causing the line to extend 2 characters past the intended widget width.

**Breakdown:**

- `" " * col` → col chars
- `"│"` → 1 char
- `"  ── "` → 5 chars
- `label` → len(label) chars
- `" " + "─" * remaining` → 1 + remaining chars
- **Total:** `col + 7 + len(label) + remaining`

Current code: `remaining = max(width - col - 5 - len(self._label), 1)` → total = `width + 2`

**Fix:** Change constant from `5` to `7`:

```python
remaining = max(width - col - 7 - len(self._label), 1)
```

This may cause visual clipping or overflow in the terminal widget.

## Suggestions

### 1. Module docstring still says "closing separator"

**File:** `teleclaude/cli/tui/widgets/group_separator.py:1`

The module-level docstring `"""Shared closing separator for project groups in tree views."""` still describes only the closing-line role. The class docstring was correctly updated to reflect both purposes. Consider aligning the module docstring.

---

## Requirements Trace

| Requirement                               | Status | Evidence                                                     |
| ----------------------------------------- | ------ | ------------------------------------------------------------ |
| API response includes `after` and `group` | ✅     | `api_models.py:192-193`, `api_server.py:1143-1144,1176-1177` |
| Dimmed dependency suffix on todo rows     | ✅     | `todo_row.py:198-201`                                        |
| Group sub-headers in Preparation view     | ✅     | `preparation.py:161-169`                                     |
| Display matches `telec roadmap` info      | ✅     | Both dependency arrows and group labels present              |
| No regressions in existing tests          | ✅     | Build gates confirm tests pass                               |

## Implementation Quality

- Field additions follow existing dataclass/DTO patterns consistently across all 6 layers
- Safe defaults (`default_factory=list`, `None`) ensure backward compatibility with cached data
- Defensive `getattr` usage in `PreparationView` matches existing pattern for other fields
- `from_dict()` deserialization handles missing fields gracefully
- `to_dict()` via `asdict()` automatically picks up new fields — no manual wiring needed
- Group tracking logic in `PreparationView` correctly handles transitions between groups and ungrouped items
- `GroupSeparator` not added to `_nav_items` — correct, separators should not be keyboard-navigable

## Verdict: REQUEST CHANGES

One important finding (off-by-2 width bug) requires a fix before approval. The fix is a single-character change (`5` → `7`).
