# agent-cli-context-preservation — Requirements

## Problem statement

The module `teleclaude/install/install_hooks.py` is misnamed: it configures
wrappers, MCP servers, notify hooks, and static CLI settings — not just hooks.
Separately, a prototype Codex compaction prompt exists in project-local `.codex/`
files, but it is not distributed through the repo-managed setup path, so other
users and environments do not receive it. Generated markdown artifacts also lack
preservation markers, meaning Codex compaction can silently discard
TeleClaude-injected context.

## Requirements

### R1 — Rename the agent CLI configurator module

The Python module at `teleclaude/install/install_hooks.py` and its thin CLI
entry point at `bin/init/install_hooks.py` must adopt a name that reflects their
actual responsibility: configuring agent CLIs (hooks, wrappers, MCP servers,
settings).

**Success criteria:**

- The old module paths no longer exist on disk after the change.
- All internal imports, call-sites, log messages, and comments reference the
  new module identity. [inferred: "log messages and comments" — input says
  "log text, comments"]
- The existing test file is renamed to match the new module identity, and all
  its import paths are updated.
- The guardrails exclusion list in `tools/lint/guardrails.py` references the
  renamed path.
- The init flow import in `teleclaude/project_setup/init_flow.py` references
  the renamed module.

### R2 — Inline the shell wrapper and remove the standalone script

The shell script `bin/init/setup_agent_hooks.sh` is a thin wrapper that calls
the Python entry point. Its behavior must be inlined directly into `bin/init.sh`,
and the standalone shell script must be removed.

**Success criteria:**

- `bin/init/setup_agent_hooks.sh` no longer exists on disk.
- `bin/init.sh` no longer sources the removed script.
- `bin/init.sh` invokes the renamed Python entry point directly using the same
  invocation pattern (PYTHONPATH, venv python, script path).

### R3 — Add a repo-owned Codex compaction prompt source

A compaction prompt file must exist within the repository under the install
settings area, so it is version-controlled and distributable alongside other
agent CLI settings.

**Success criteria:**

- The compaction prompt content instructs Codex to preserve content between
  the context-preservation markers (see R5) verbatim across compaction.
- The prompt is stored within the repository in a location consistent with other
  install-time settings. [inferred: `teleclaude/install/settings/` is the
  existing pattern]

### R4 — Deploy the compaction prompt through the agent CLI configurator

The renamed configurator (R1) must deploy the repo-owned compaction prompt to the
user's Codex config directory and configure Codex to use it.

**Success criteria:**

- The compaction prompt is written to `~/.codex/` during configuration.
- The Codex TOML config at `~/.codex/config.toml` includes the
  `experimental_compact_prompt_file` key pointing to the deployed prompt filename.
- The deployment is idempotent: re-running configuration does not corrupt the
  file or duplicate entries.
- The Codex setting is integrated into the existing settings override mechanism
  (`teleclaude/install/settings/codex.json`) rather than being hard-coded in the
  configurator logic.

### R5 — Wrap generated markdown artifacts with context-preservation markers

The distribution script (`scripts/distribute.py`) must wrap its generated
markdown outputs with the markers
`<!-- TELECLAUDE_CONTEXT_PRESERVATION_START -->` and
`<!-- TELECLAUDE_CONTEXT_PRESERVATION_END -->`.

**Success criteria:**

- All markdown outputs produced by the distribution pipeline contain the start
  marker before the content and the end marker after the content.
- Non-markdown outputs (Gemini TOML) are not wrapped — the markers are
  HTML comments and would be invalid in TOML.
- Existing file structure and formatting are preserved; the markers are
  added as a wrapping layer, not embedded within the document body.

### R6 — Remove the prototype files

The temporary project-local `.codex/config.toml` and
`.codex/CODEX.compaction.md` files are superseded by the repo-managed path
(R3, R4) and must be removed.

**Success criteria:**

- `.codex/config.toml` and `.codex/CODEX.compaction.md` (in the main
  repository, not in `~/.codex/`) no longer exist on disk after the change.
- No references to these prototype paths remain in committed code. [inferred]

### R7 — Test coverage for changed and new behaviors

All renamed, modified, and new code paths must have corresponding test coverage.

**Success criteria:**

- The renamed configurator module has tests covering its existing behavior
  (carried forward from the existing characterization tests).
- The compaction prompt deployment logic (R4) is tested: file writing,
  idempotency, and TOML key insertion.
- The markdown marker wrapping (R5) is tested: markdown outputs receive markers,
  non-markdown outputs do not.
- All tests pass via pre-commit hooks.

## Scope boundaries

- The rename (R1, R2) and the context-preservation feature (R3-R6) are a single
  coherent delivery. The rename is a prerequisite for clarity but all items ship
  together.
- The distribution script's internal structure and transform pipeline are not
  being redesigned — only marker wrapping is added to its output path.
- No new agent artifact type is created for the compaction prompt. [explicit
  from input]
- The existing `teleclaude/install/settings/codex.json` settings override
  mechanism is reused — no new configuration surface is introduced.

## Deferred / out of scope

- Compaction prompt content for agents other than Codex.
- Refactoring the distribution script beyond the marker-wrapping addition.
- Changes to the `.codex/prompts/` directory (managed by distribution, not by
  the configurator).
