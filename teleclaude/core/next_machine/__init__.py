"""Next-machine package with shared core and stage-specific state machines.

This package intentionally has an empty __init__: callers must import from the
specific submodule that owns the symbol they need (e.g.
``teleclaude.core.next_machine.delivery``,
``teleclaude.core.next_machine.prepare_events``,
``teleclaude.core.next_machine._types``). Eager re-exports here would force
every consumer — including lightweight callers like the hook receiver — to
load the entire state-machine surface and would create circular imports
through ``todos_db``.
"""
