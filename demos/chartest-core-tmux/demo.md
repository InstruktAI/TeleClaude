# Demo: chartest-core-tmux

## Validation

```bash
. .venv/bin/activate && pytest tests/unit/core/tmux_bridge -v
```

## Guided Presentation

Start by running the validation block. The presenter should point out that the suite is a pure characterization safety net for the tmux bridge modules, not a production behavior change.

Then walk through the four test files and what each one pins:

1. `test__keys.py` proves delegation, tty injection fallback, signal mapping, and special-key tmux sequences.
2. `test__pane.py` proves pane capture, session diagnostics, shell-readiness polling, and pipe-pane helpers.
3. `test__session.py` proves session temp-dir cleanup, bootstrap environment injection, shell guardrails, and ensure/update flows.
4. `test__subprocess.py` proves timeout handling kills hung subprocesses and raises structured errors.

The key observation is that future tmux bridge refactors now have file-level regression coverage at the module boundaries listed in the todo requirements.
