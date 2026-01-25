# Stateless Command Policy — Policy

Commands are atomic, explicit, and idempotent. They state required setup, perform the work, and end with a verifiable outcome.

## Rules

- **Make prerequisites explicit**: include required setup as part of the command flow.
- **Declare the working state**: state what the command relies on and what it produces.
- **Single responsibility**: one command completes one job end-to-end.
- **Idempotent execution**: repeat runs converge on the same correct result.

When sequencing is needed, use orchestration or a state machine to compose commands.
