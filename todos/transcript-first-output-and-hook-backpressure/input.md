# Input: transcript-first-output-and-hook-backpressure

Core architecture concern:

- Output currently has dual producers (hook-driven and poller-driven), causing duplicated work and noisy fanout.
- Native transcript/session files should be the source of truth for output, including tool activity rendering.
- Hook events can arrive in bursts and process late; backlog should not delay UI output.

Desired direction:

- One cadence-driven output producer.
- Hooks remain for control-plane state changes.
- Add backpressure/coalescing so burst traffic stays bounded.
