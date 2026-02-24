# Input: ucap-truthful-session-status

Parent:

- `unified-client-adapter-pipeline`

Objective:

- Make core the source of truth for session lifecycle UX status.
- Keep adapters as presentation translators that map one canonical status contract
  to each client's capabilities.

Context:

- Depends on `ucap-canonical-contract`.
- Builds on `transcript-first-output-and-hook-backpressure` being completed as the
  output data-plane foundation.
