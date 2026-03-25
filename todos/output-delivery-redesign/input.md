# Output Delivery Redesign

## Problem

The output delivery system accumulated layers of complexity: core pushes content to adapters via `send_output_update`, `send_threaded_output`, `broadcast_user_input`; the agent coordinator manages render digests, turn breaks, echo guards, and actor name resolution; QoS schedulers sit between core and adapters. This creates fragile coupling, stale in-memory state bugs (the origin_metadata regression), duplicate reflections, and silent delivery failures.

## Solution

Adapters pull output on their own cadence. Core only signals activity via lifecycle events. No output data flows from core to adapters. Each adapter reads transcript files directly and renders at its own rate limit interval.

## Changes Made

1. **Staleness fix** — `_has_active_output_message` fetches fresh session from DB
2. **Removed broadcast_user_input** — core no longer pushes user input reflections to adapters; removed actor name resolution, echo guard, identity helpers
3. **Removed THREADED_OUTPUT flag** — all adapters use threaded output unconditionally; deleted feature_flags.py, edit-in-place code paths
4. **Adapter-owned output pull** — new OutputCadenceLoop; removed \_IncrementalOutputMixin, HeadlessSnapshotService; polling coordinator just updates last_activity_at
5. **Cruft cleanup** — removed dead send_output_update/send_threaded_output from adapter client
