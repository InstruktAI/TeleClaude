<!-- no-demo: This delivery modifies internal state machine logic and CLI subcommand routing. All behavior is verified through unit tests (test_next_machine_hitl.py, test_next_machine_demo.py, test_next_machine_state_deps.py, test_next_machine_deferral.py). There is no standalone executable demo — the changes are infrastructure enforcement that activates during orchestrator-driven workflows. -->

# Demo: lifecycle-enforcement-gates

This delivery adds build gates (test suite + demo validation) to the state machine and refactors `telec todo demo` into explicit subcommands. The changes are internal infrastructure — validated by 1868 passing unit tests, not a standalone demo script.
