# Help Desk Platform — Implementation Plan

## Phase 1: Configuration Refactor

Refactor the static configuration to support multiple profiles.

- [ ] **Update `teleclaude/constants.py`**:
  - Change `AGENT_PROTOCOL` structure. Replace the flat `flags` string with a `profiles` dictionary.
  - Define `default` (existing flags) and `restricted` (new safe flags) for `claude`, `gemini`, `codex`.
- [ ] **Update `teleclaude/config/__init__.py`**:
  - Update `AgentConfig` dataclass to hold a `profiles` dict instead of `flags` str.
  - Update `_build_config` to parse this new structure.
- [ ] **Update `teleclaude/core/agents.py`**:
  - Update `get_agent_command` signature to accept `profile: str = "default"`.
  - Logic: Look up flags from `agent_config.profiles[profile]`.

## Phase 2: The Routing Logic (The Trap)

Implement the forced routing in the session handler, integrating with `person-identity-auth` plumbing.

- [ ] **Modify `create_session` in `teleclaude/core/command_handlers.py`**:
  - **Identity Check:** Retrieve `IdentityContext` (via `get_identity_resolver` or command metadata).
  - **Branching:**
    - **If Admin/Member:** Proceed as normal (allow `project_path` selection, use `default` profile).
    - **If Newcomer/External:**
      - **Force Path:** Set `project_path = resolve_project_path("help-desk")`.
      - **Force Profile:** Set `profile = "restricted"`.
      - **Log:** Log a warning that the session was trapped/redirected.
  - **Pass Down:** Ensure the selected `profile` is passed to `start_agent` / `get_agent_command`.

## Phase 3: Project Scaffolding

Set up the physical jail.

- [ ] **Create Directory:** `mkdir help-desk` in repo root.
- [ ] **Claude Security:** Create `help-desk/.claude/settings.json` with strict `deny` rules for parent traversal.
- [ ] **Documentation:** Add a `README.md` in `help-desk/` explaining its purpose (this is visible to the Agent).

## Phase 4: Verification

- [ ] **Unit Test:** Add test in `test_command_handlers.py` ensuring `create_session` overrides path for non-admins.
- [ ] **Manual Verification:**
  - Start a session as "customer".
  - Try to read a file outside the directory.
  - Verify it fails.
  - Try to read a global doc.
  - Verify it succeeds.
