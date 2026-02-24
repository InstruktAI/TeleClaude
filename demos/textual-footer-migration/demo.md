# Demo: textual-footer-migration

## Validation

```bash
# Verify ActionBar widget is gone
! test -f teleclaude/cli/tui/widgets/action_bar.py
```

```bash
# Verify no ActionBar references remain in codebase
! grep -r "ActionBar" teleclaude/cli/tui/ --include="*.py"
```

```bash
# Verify no CursorContextChanged references remain
! grep -r "CursorContextChanged" teleclaude/cli/tui/ --include="*.py"
```

```bash
# Verify Footer is used in app.py
grep -q "Footer" teleclaude/cli/tui/app.py
```

```bash
# Verify all views use Binding objects (not bare tuples in BINDINGS)
python3 -c "
from teleclaude.cli.tui.views.sessions import SessionsView
from teleclaude.cli.tui.views.preparation import PreparationView
from teleclaude.cli.tui.views.jobs import JobsView
from teleclaude.cli.tui.views.config import ConfigView
from textual.binding import Binding
for view in [SessionsView, PreparationView, JobsView, ConfigView]:
    for b in view.BINDINGS:
        assert isinstance(b, Binding), f'{view.__name__} has non-Binding: {b}'
print('All views use Binding objects')
"
```

```bash
# Tests pass
make test
```

```bash
# Lint passes
make lint
```

## Guided Presentation

1. **Start the TUI**: `telec` — observe the footer area at the bottom. It should be 2 lines total: 1 line of key hints (Footer) and 1 line of status indicators (StatusBar).

2. **Sessions tab**: The footer shows SessionsView bindings — arrows for navigation, Space for preview/sticky, Enter for focus, n/k/R for session management. Navigation keys should appear grouped with Unicode symbols.

3. **Switch to Preparation** (press `2`): The footer automatically updates to show PreparationView bindings — Enter/Space/n/b/p/s/R. No code change was needed for this — Footer auto-discovers from the focused view.

4. **Switch to Jobs** (press `3`): Footer shows only JobsView bindings (up/down/Enter). Simpler view = simpler footer. Automatic.

5. **Switch to Config** (press `4`): Footer shows ConfigView bindings with Tab/Shift+Tab and arrow keys.

6. **Theme check**: Press `t` to cycle pane theming — verify the footer keys remain readable across all theme variants.

7. **Key point**: Add a new binding to any view's `BINDINGS` list, reload with SIGUSR2, and it appears in the footer instantly. The bug class that prompted this todo is eliminated.
