# Input: ucap-canonical-contract

Parent:

- `unified-client-adapter-pipeline`

Objective:

- Define one canonical outbound realtime contract used by all client adapters.
- Establish shared serializer/validation primitives for adapter fanout.

Context:

- Must follow `transcript-first-output-and-hook-backpressure` completion.
- This todo defines contract primitives only; client lane migrations happen in downstream todos.
