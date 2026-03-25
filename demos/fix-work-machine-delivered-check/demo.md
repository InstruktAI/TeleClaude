# Demo: fix-work-machine-delivered-check

## Validation

```bash
# Regression tests for delivered slugs with cleaned-up state.
pytest -q tests/unit/core/next_machine/test_slug_resolution.py -k "returns_done_for_delivered_slug_with_no_state_yaml or raises_on_slug_in_both_delivered_and_roadmap"
```

```bash
# A delivered slug with no state.yaml resolves to done.
uv run python - <<'PY'
from pathlib import Path
from tempfile import TemporaryDirectory

from teleclaude.core.next_machine.slug_resolution import get_item_phase

with TemporaryDirectory() as tmp:
    root = Path(tmp)
    todos = root / "todos"
    todos.mkdir()
    (todos / "delivered.yaml").write_text(
        "- slug: delivered-slug\n  date: '2026-03-20'\n",
        encoding="utf-8",
    )
    print(f"phase={get_item_phase(str(root), 'delivered-slug')}")
PY
```

```bash
# A slug present in both delivered.yaml and roadmap.yaml fails fast as a data integrity error.
uv run python - <<'PY'
from pathlib import Path
from tempfile import TemporaryDirectory

from teleclaude.core.next_machine._types import RoadmapEntry
from teleclaude.core.next_machine.roadmap import save_roadmap
from teleclaude.core.next_machine.slug_resolution import get_item_phase

with TemporaryDirectory() as tmp:
    root = Path(tmp)
    todos = root / "todos"
    todos.mkdir()
    slug = "ambiguous-slug"
    (todos / "delivered.yaml").write_text(
        f"- slug: {slug}\n  date: '2026-03-20'\n",
        encoding="utf-8",
    )
    save_roadmap(str(root), [RoadmapEntry(slug=slug, group=None, after=[], description=None)])

    try:
        get_item_phase(str(root), slug)
    except ValueError as exc:
        print("raised=data-integrity" if "data integrity" in str(exc) else str(exc))
    else:
        raise SystemExit("expected ValueError")
PY
```

## Guided Presentation

Start with the regression test block. It should pass both new tests, proving the
delivered-first lookup and the ambiguity guard are covered permanently.

Run the second block next. The output should be `phase=done`, even though no
`state.yaml` exists for the slug. This is the failure that previously surfaced
as `ITEM_NOT_READY` through `telec todo work`.

Run the third block last. It should print `raised=data-integrity`, showing that
the resolver now fails fast instead of silently choosing one source of truth
when `delivered.yaml` and `roadmap.yaml` disagree.
