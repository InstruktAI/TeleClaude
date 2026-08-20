---
description: 'Local Kimi Code 0.37.2 research record: evidence captured, vendor-document drift, and unresolved runtime questions.'
---

# Kimi Code Research Log

## 2026-08-20 — Runtime corpus grounding

### Verified locally

- The target binary reports version 0.37.2 and is not discoverable through the
  current shell's `PATH`.
- `config.toml`, `tui.toml`, sessions, workspace-trust records, logs, and
  `workspaces.json` exist under the configured Kimi home.
- The CLI help exposes prompt, model, session, permission, plan, workspace,
  Skill, agent, provider, export, ACP, login, doctor, visualizer, migration,
  and update surfaces documented in this corpus.
- Hook strings include `hookSpecificOutput`, `permissionDecision`, and
  `permissionDecisionReason`; `additionalContext` occurs zero times in the
  installed binary.
- Workspace-trust records have `root` and `trustedAt` fields.

### Vendor-document drift

The current vendor Hooks documentation describes more hook behavior than was
accepted as established for the installed 0.37.2 runtime. This corpus records
the installed binary's permission-decision-only hook envelope and does not
infer a context-injection channel from the newer guide.

### Unresolved

- Live hook payloads, registration, and stdout/exit-code behavior.
- Exact project/user/extra precedence when all configuration and extension
  roots collide.
- Stream JSON, custom-agent execution, ACP execution, and updater behavior.

## Sources

- https://moonshotai.github.io/kimi-code/
- https://moonshotai.github.io/kimi-code/en/customization/hooks
- https://moonshotai.github.io/kimi-code/en/configuration/config-files
