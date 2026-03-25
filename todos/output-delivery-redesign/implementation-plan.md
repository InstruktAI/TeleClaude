# Implementation Plan: Output Delivery Redesign

## Task 1: Fix staleness regression

- Make `_has_active_output_message` async, fetch fresh session from DB
- Update callers in `_incremental.py` to await

## Task 2: Remove broadcast_user_input and actor name resolution

- Delete `broadcast_user_input` from adapter client
- Delete actor resolution functions from `_helpers.py`
- Remove echo guard and broadcast calls from coordinator
- Remove `_broadcast()` from `deliver_inbound`

## Task 3: Remove THREADED_OUTPUT flag and edit-in-place output

- Delete `feature_flags.py`
- Remove `THREADED_OUTPUT` from UiAdapter and subclasses
- Make `send_output_update` and `_send_footer` no-ops
- Remove `any_adapter_wants_threaded_output`

## Task 4: Adapter-owned output pull

- Modify PollingCoordinator to update `last_activity_at` instead of pushing
- Create `OutputCadenceLoop` in `adapters/ui/output_cadence.py`
- Add cadence loop to UiAdapter base class and Discord adapter
- Remove `_IncrementalOutputMixin`, `HeadlessSnapshotService`
- Remove headless pull mechanism from coordinator

## Task 5: Clean up dead code

- Remove `send_output_update` and `send_threaded_output` from adapter client
