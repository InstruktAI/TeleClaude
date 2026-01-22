# Stateless Command Policy

Commands must be **atomic** and **idempotent**. They cannot assume hidden state or ask for conditional actions that require unknown checks.

## Rules

- **No conditional pre-steps**: Do not say “if X is stale, then run Y.” If a step is required, run it as part of the command.
- **No hidden prerequisites**: Commands must not depend on implicit or undisclosed state.
- **Single responsibility**: One command does one job end-to-end.
- **Idempotent**: Re-running a command should produce a correct result without manual cleanup.

If sequencing is required, use the orchestration layer or a state machine, not conditional text inside a command.
