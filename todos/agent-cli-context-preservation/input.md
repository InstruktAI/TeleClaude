# agent-cli-context-preservation — Input

Goal
Rename the misnamed agent CLI configuration path and complete the repo-managed Codex compaction prompt + context preservation work.

Why
The current name install_hooks is misleading because the implementation already configures wrappers, MCP servers, notify hooks, and static CLI settings. We also prototyped a custom Codex compaction prompt in project-local .codex files, but the durable solution must flow through repo-managed setup and distribution so other users get the same behavior.

Scope
1. Rename teleclaude/install/install_hooks.py to teleclaude/install/configure_agent_clis.py.
2. Rename bin/init/install_hooks.py to bin/init/configure_agent_clis.py.
3. Remove bin/init/setup_agent_hooks.sh entirely and inline its tiny wrapper behavior into bin/init.sh.
4. Update all imports, callsites, log text, comments, and tests so the concept is configure agent CLIs instead of install hooks.
5. Add a repo-owned Codex compaction prompt source under teleclaude/install/settings.
6. Extend the renamed Codex CLI configurator so it deploys that prompt to ~/.codex/teleclaude.compaction.md and writes experimental_compact_prompt_file = "teleclaude.compaction.md" into ~/.codex/config.toml.
7. Add that Codex setting to teleclaude/install/settings/codex.json so make install and telec init deploy it idempotently through the existing repo-managed Codex settings path.
8. Update scripts/distribute.py so generated markdown artifacts are wrapped with the exact uppercase markers <!-- TELECLAUDE_CONTEXT_PRESERVATION_START --> and <!-- TELECLAUDE_CONTEXT_PRESERVATION_END -->.
9. Apply marker wrapping only to markdown outputs so Gemini TOML remains valid.
10. Update the custom Codex compaction prompt so it explicitly preserves any content between those markers verbatim across compaction.
11. Remove the temporary prototype files .codex/config.toml and .codex/CODEX.compaction.md once the repo-managed path is in place.
12. Add or update unit tests for the renamed configurator, Codex config writing, compaction prompt deployment, and markdown marker wrapping.

Implementation notes
- Keep ownership boundaries clear: the renamed configure_agent_clis path owns runtime CLI config in home directories, while telec sync / scripts/distribute.py owns generated artifact content.
- Do not invent a new agent artifact type for the compaction prompt. A raw compaction prompt file does not fit the existing normalized command/skill/agent schemas.
- Use the existing settings override mechanism in teleclaude/install/settings/codex.json rather than keeping ad hoc project-local .codex config as the long-term source of truth.
- Preserve valid file formats: only markdown gets HTML comment markers.

Verification
- Update or rename tests under tests/unit/install/ for the configurator rename and Codex config path.
- Add tests for the marker wrapper in generated markdown outputs.
- Run the relevant unit tests.
- Run telec sync after the changes and confirm distribution still succeeds aside from any unrelated pre-existing warn-only issues.

Outcome
A repo-managed, idempotent Codex compaction customization path with explicit context preservation markers, plus a correctly named agent CLI configuration surface.
