# Task 7: Promote target_computer and actor context to named fields in MessageMetadata

## Context

Redis transport and fanout coordinator currently use deprecated `MessageMetadata.channel_metadata` dict for target_computer routing and actor context. These are core message properties that deserve named fields.

## Scope

- Add named fields to MessageMetadata (target*computer, actor*\*) — approximately 5 fields
- Update Redis serialization (\_messaging.py, \_request_response.py)
- Update fanout coordinator to populate/read named fields
- Update all callers to use named fields
- Remove channel_metadata usage for these purposes

## Success Criteria

- MessageMetadata has typed, named fields for target_computer and actor context
- Redis serialization/deserialization maintains contract
- Fanout coordinator routes using named fields
- All message sources populate named fields
- Tests verify routing behavior
- No regressions in message delivery
