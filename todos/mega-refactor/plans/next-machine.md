# next_machine.py

- Move formatting/templates to `core/next_machine/formatters.py`.
- Move git/fs IO to `core/next_machine/git_state.py`.
- Move fallbacks/constants to `core/next_machine/config.py`.
- Keep state logic in `core/next_machine/state_machine.py`.
- `next_machine.py` becomes facade.
