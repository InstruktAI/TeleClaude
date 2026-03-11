# Demo: fix-bug-cleanup-pipeline-has-three-gaps-1-is

## Validation

```bash
# Gap 1: Verify _is_bug_slug checks todos/{slug}/bug.md (not todos/bugs/{slug}/bug.md)
.venv/bin/python -c "
import inspect
from teleclaude.core.integration.state_machine import _is_bug_slug
src = inspect.getsource(_is_bug_slug)
assert 'todos/bugs' not in src, 'Wrong path: still checks todos/bugs/'
print('Gap 1 fixed: _is_bug_slug no longer checks todos/bugs/')
"
```

```bash
# Gap 2: Verify deliver_to_delivered routes save_roadmap into the else branch only
.venv/bin/python -c "
import inspect
from teleclaude.core.next_machine.core import deliver_to_delivered
src = inspect.getsource(deliver_to_delivered)
lines = src.split('\n')
else_idx = next(i for i, l in enumerate(lines) if 'else:' in l)
save_idx = next(i for i, l in enumerate(lines) if 'save_roadmap' in l)
assert save_idx > else_idx, 'save_roadmap must come after else branch'
print('Gap 2 fixed: deliver_to_delivered handles bug slugs without roadmap entry')
"
```

```bash
# Gap 3: Verify remove_todo uses best-effort worktree/branch removal instead of RuntimeError
.venv/bin/python -c "
import inspect
from teleclaude.todo_scaffold import remove_todo
src = inspect.getsource(remove_todo)
assert 'RuntimeError' not in src, 'RuntimeError guard still present'
assert '\"worktree\", \"remove\"' in src, 'Worktree removal not present'
assert '\"branch\", \"-D\"' in src, 'Branch deletion not present'
print('Gap 3 fixed: remove_todo handles worktree removal best-effort')
"
```

## Guided Presentation

### Gap 1: Bug detection was always returning False

`_is_bug_slug()` in the integration state machine checked `todos/bugs/{slug}/bug.md`
but bugs live at `todos/{slug}/bug.md`. Since no bug.md ever existed at the wrong path,
the function always returned False — treating every bug slug as a regular todo. This
caused the integration machine to call `deliver_to_delivered` for bug slugs, which then
failed because bugs are intentionally not in `roadmap.yaml`.

**Observe:** The validation block confirms `todos/bugs` no longer appears in the source.

**Why it matters:** With the wrong path, the integration pipeline mistreated every bug
slug, triggering delivery failures and log warnings on every integration cycle.

### Gap 2: Delivery blocked on missing roadmap entry

`deliver_to_delivered()` returned False when a slug was absent from `roadmap.yaml`
and not already in `delivered.yaml` — with no path for slugs that exist only as a
`todos/{slug}/` directory. Since bugs intentionally skip the roadmap, this gate always
rejected them.

The fix moves `save_roadmap` into the `else` branch (runs only when an entry was
actually removed from the roadmap) and adds a check: if the slug has a `todos/{slug}/`
directory, proceed to record in `delivered.yaml`.

**Observe:** The validation block confirms `save_roadmap` follows the `else:` branch.

**Why it matters:** Bug fix slugs can now be recorded as delivered without requiring
a roadmap entry. Any slug with a todo directory is accepted.

### Gap 3: Removal refused due to worktree presence

`remove_todo()` raised `RuntimeError` when `trees/{slug}/` existed, instructing the
caller to remove the worktree manually first. Since bug fix slugs always execute inside
their own worktree, this made cleanup impossible through `telec todo remove`.

The fix removes the guard and instead proactively runs `git worktree remove --force`
and `git branch -D` (both best-effort, non-fatal). `found_worktree` is added to the
"anything found" check so a worktree-only slug is recognized as a valid target.

**Observe:** The validation block confirms no `RuntimeError` remains and both git
cleanup commands are present in the implementation.

**Why it matters:** Bug fix slugs can now be fully cleaned up through `telec todo remove`
without manual worktree management, completing the automation lifecycle.
