# Input: unified-client-adapter-pipeline

Architectural objective:

- Harmonize Web and TUI with the same adapter pipeline used by other adapters.
- Avoid direct client bypass paths tied to event bus/API-proxy specifics.
- Keep one realtime stream contract for both web frontend and TUI consumers.

Context:

- Transcript-first output pipeline and hook backpressure work (separate todo) is the prerequisite.
- This todo focuses on client/adaptation unification once output data plane is clean.
