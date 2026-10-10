---
description: Official Codex-managed subscription authentication lifecycle for private CI, including refresh persistence and non-interactive structured output.
---

# Codex-managed authentication in private CI

OpenAI documents a managed-account path for trusted private automation that needs
ChatGPT/Codex subscription entitlements. This path uses a dedicated file-backed
login created with `codex login`. It applies to Codex-managed ChatGPT credentials,
not external-token host integrations.

An ephemeral runner restores the current authentication cache from secure storage,
runs Codex, and persists the updated cache. Codex performs its own refresh and
retry; callers do not implement the OAuth refresh protocol. One cache belongs to
one serialized execution stream. Replaying its original seed on every run loses
the refresh state. Failed or revoked refresh credentials require reseeding.

`codex exec` reuses saved authentication and supports a JSON Schema for its final
response through `--output-schema`. The schema constrains the final report;
execution errors are a separate outcome. Native permission profiles can restrict
agent-command filesystem and network access. Those profiles constrain commands,
not the authentication work performed by the Codex process itself.

## Limits

The managed-auth guide excludes public/open-source repositories. It specifies
the secure restore/run/persist lifecycle, not a particular secret-storage product.
It does not promise that a login remains valid indefinitely or establish the
isolation of a particular deployed workflow.

## Sources

- https://learn.chatgpt.com/docs/auth/ci-cd-auth
- https://learn.chatgpt.com/docs/non-interactive-mode
- https://learn.chatgpt.com/docs/permissions
