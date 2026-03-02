# Implementation Plan: fix-telec-sessions-end-does-not-support-self

## Tasks

- [x] Import `_read_caller_session_id` from `tool_client` into `tool_commands`
- [x] Add `self` alias resolution in `handle_sessions_end` after argument parsing
- [x] Exit with clear error if `self` resolution fails (no session file)
- [x] Update `-h` docstring to document `self` as a valid session_id value
- [x] Add unit tests: self-resolves, self-fails-gracefully, literal-id-unchanged
