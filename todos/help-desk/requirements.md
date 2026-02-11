# Help Desk Platform — Requirements

## Goal

Establish `help-desk` as the universal entry point for external interactions. It serves as a secure "Lobby" where customers are jailed and admins act as supervisors.

## Research Input (Required)

These specs define the security boundaries and configuration overrides required for this platform.

- `docs/third-party/claude-code/permissions.md` — Configuration for CWD restriction and denial rules.
- `docs/third-party/gemini-cli/permissions.md` — Configuration for sandbox and directory mounting.
- `docs/third-party/codex-cli/permissions.md` — Configuration for profile-based autonomy.

## Core Requirements

1.  **Universal Ingress (The Lobby)**
    - **Forced Path:** Any session originating from an external adapter (WhatsApp, Discord, Web) **MUST** be rooted in `help-desk`.
    - **Invariant:** `create_session` overrides `project_path` to `help-desk` for these origins.

2.  **Dual-Profile Agent Launch**
    - **Admin Role:** Launches with `profile="default"` (Unrestricted). Can use `teleclaude__start_session` to spawn agents in other projects.
    - **Customer Role:** Launches with `profile="restricted"` (Jailed). Cannot spawn child sessions.
    - **Selection:** Derived from `IdentityContext` (from `person-identity-auth`).

3.  **Agent Configuration (`constants.py`)**
    - Refactor `AGENT_PROTOCOL` to support named profiles:
      - `default`: `--dangerously-skip-permissions` (Claude), `--yolo` (Gemini).
      - `restricted`: `permissions.deny` (Claude), `--sandbox` (Gemini).

4.  **Filesystem Jailing**
    - **Claude:** `help-desk/.claude/settings.json` denies parent access (`../*`) and system paths.
    - **Mounts:** Explicitly mount `~/.teleclaude/docs` for knowledge access via CLI flags defined in research specs.

## Success Criteria

- External requests _always_ land in `help-desk`.
- Admins in `help-desk` can spawn a new agent in `backend-repo`.
- Customers in `help-desk` cannot read `../config.yml`.
- Customers in `help-desk` CAN read `~/.teleclaude/docs/baseline.md`.
