## Build Gates (Builder)

- [x] Task 1: Define the planned-change construct in `doc_body.py`.
- [x] Task 2: Wire the reader lens and pending-changes awareness header in `context_selector.py`.
- [x] Task 3: Detect planned-change markers in index `superseded_by` derivation.
- [x] Task 4: Reconcile planned-change blocks on delivery in `docs_reconcile.py`.
- [x] Task 5: Validate the planned-change triple-marker shape.
- [x] Task 6: Document the change-shape heuristic, planned-change construct, and related-files discovery.
- [x] Task 7: Reflect the planned-change construct in `snippet-authoring-schema`.
- [x] Task 8: Extend the doc-hygiene review lane with companion re-sync and planned-change scope.
- [x] Task 9: Reflect the behavioral delta in the four project context feature specs.

### Verification

- `uv run pytest tests/context/test_doc_snippet_three_phase_retrieval.py tests/context/test_index_shape.py tests/quality/test_docs_reconcile.py tests/quality/test_doc_validation_scoping.py --snapshot-update`: PASS (`21 passed`; snapshots updated for intended output deltas).
- `uv run pytest tests/quality/test_doc_validation_scoping.py tests/context/test_doc_snippet_three_phase_retrieval.py tests/context/test_index_shape.py tests/quality/test_docs_reconcile.py`: PASS (`21 passed`; `13 snapshots passed`).
- Scoped changed-snippet validation via `validate_all_snippets(root, paths=[...changed docs...])`: PASS.
- `telec code test`: PASS (`21 passed`; `13 snapshots passed`).
- `telec code lint`: PASS. Markdown validation, Ruff, Pyright, Mypy, and duplicate scan passed; formatter updated four changed files.
- `telec sync`: BLOCKED by pre-existing validation findings in `docs/global/software-development/design/guardrails-engine.md` outside this task scope (`snippet_see_also_bad_prefix`, two `snippet_invalid_inline_ref` findings).

### User-Facing Verification

- No browser or web UI path changed.
- CLI/doc retrieval behavior was verified at the functional boundary: phase-1 output renders `superseded by`, phase-2 default reads render current planned-change content plus the awareness header, targeted reads render replacement content without the awareness header.
- Delivery and validation behavior were verified at their public boundaries: reconciliation rewrites only the delivered slug's planned-change block and is idempotent; snippet validation accepts well-formed blocks and reports malformed marker shape.
