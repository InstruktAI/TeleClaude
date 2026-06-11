## Build Gates (Builder)

- [x] Task 1: Add `schema_version` to the Rust `EventEnvelope` with a tolerant default.
- [x] Task 2: Pin tolerant unknown-field decode at the Rust subscribe boundary.
- [x] Task 3: Add `schema_version` to the Python `ClusterEnvelope` with tolerant decode.
- [x] Task 4: Stamp `schema_version` in the Python cluster publisher.
- [x] Task 5: Audit existing cross-node consumers against the tolerant-reader rule.
- [x] Task 6: Reflect the behavioral delta in the doc layer.

### Verification

- `cargo test -p event-bus`: PASS (`6 passed`; Redis integration test ignored because no Redis service is running).
- `uv run pytest tests/integration/test_cluster_envelope.py`: PASS (`5 passed`).
- Tolerant-reader audit: PASS. No Rust `deny_unknown_fields` hits under `crates/`; Python `extra="forbid"` hits are limited to `teleclaude/api_models.py` request payloads and `teleclaude/types/todos.py` query/state validation, not cross-node event consumers.

### User-Facing Verification

- No browser or UI path changed.
- Wire-contract behavior was verified at the event decoding boundaries: Rust `EventEnvelope` decodes absent `schema_version` as v1 and ignores unknown top-level fields; Python `ClusterEnvelope` decodes absent `schema_version` as v1, ignores unknown extra keys, rejects malformed known `schema_version`, and round-trips publisher output through `decode_envelope`.
