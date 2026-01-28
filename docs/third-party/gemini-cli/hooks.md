# Gemini CLI Hooks

## Overview

Gemini CLI hooks run local commands at lifecycle events. Hooks are configured in settings
and receive JSON payloads describing the event.

## Note on hooks.enabled warning

Gemini CLI may emit a validation warning when `"hooks.enabled": true` is present in
`~/.gemini/settings.json` (e.g., “Expected array, received boolean”). In practice,
the runtime still honors `hooks.enabled` and hooks fire correctly. This appears to be
an upstream schema/validation mismatch; keep `hooks.enabled` set to true and ignore
the warning unless/until Gemini fixes the validator.

## Sources

- https://geminicli.com/docs/hooks
- https://geminicli.com/docs/hooks/reference
