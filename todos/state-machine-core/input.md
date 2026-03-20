# state-machine-core — Input

Foundation for the state machine versioning work. Split from the parent
`state-machine-versioning` because the full scope (engine + migration + all
consumer adoption + mark-* elimination + ghost artifact removal) exceeds a
single builder session.

This child delivers: the engine, v1->v2 migration, CLI/API surface, and initial
adoption in the prepare router and work-readiness check. The follow-up
`state-machine-adoption` handles the remaining consumer migration.

See parent `todos/state-machine-versioning/input.md` for the full problem
statement and motivation.
