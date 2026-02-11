# Requirements: cross-project-context

## Goal

Enable `get_context` to serve documentation from multiple TeleClaude-aware projects through three-phase progressive disclosure, with role-based visibility filtering:

- **Phase 0**: Discover which projects exist (project catalog).
- **Phase 1**: Browse snippet indexes for selected projects + global docs.
- **Phase 2**: Retrieve full snippet content (unchanged from today).
- **Visibility**: Snippets are `public` or `internal`. Non-admin callers only see `public` snippets.

This allows a helpdesk agent (or any cross-project consumer) to find and retrieve documentation without knowing upfront which project holds the answer, while ensuring internal documentation stays hidden from restricted roles.

## Scope

### In scope:

- Project manifest file (`~/.teleclaude/projects.yaml`) listing all registered projects.
- `telec sync` registers the current project in the manifest.
- `description` field added to `ProjectConfig` schema.
- `get_context` gains `list_projects` (phase 0) and `projects` (phase 1 filter) parameters.
- Cross-project snippet ID rewriting: `project/` prefix replaced with lowercase project name (e.g. `teleclaude/design/...`).
- `SnippetMeta` enriched with `source_project`, `project_root`, and `visibility` for cross-project path resolution and access control.
- `visibility: public | internal` frontmatter field on snippets (default: `internal`).
- Role-based filtering: `get_context` resolves caller role from `caller_session_id` → session → stored `user_role`. Non-admin roles only see `public` snippets.
- In-memory cache of loaded indexes with mtime-based invalidation.
- Delete dead code: `project_registry.py` and `test_project_registry.py`.

### Out of scope:

- Cross-project `Required reads` resolution (snippets can only require within their own project or global).
- Other projects publishing global-scope docs (only TeleClaude publishes global docs).
- UI changes in TUI or Telegram adapters.
- Changes to the `telec sync` index-building logic (indexes are already correct; we only add registration).
- Fine-grained per-snippet ACLs beyond public/internal.

## Success Criteria

- [ ] `get_context(list_projects=True)` returns the project catalog from `~/.teleclaude/projects.yaml`.
- [ ] `get_context(projects=["teleclaude"], areas=["design"])` returns snippet index from TeleClaude's project docs + global docs.
- [ ] `get_context(projects=["teleclaude", "itsup"])` returns merged snippet indexes from both projects.
- [ ] Cross-project snippet IDs use lowercase project name as prefix instead of `project/`.
- [ ] `get_context(snippet_ids=["teleclaude/design/architecture/checkpoint-system"])` retrieves the correct file from TeleClaude's project root.
- [ ] Single-project mode (no `projects` param) behaves identically to today (backward compatible).
- [ ] `telec sync` updates `~/.teleclaude/projects.yaml` with the current project's entry.
- [ ] `project_registry.py` and its test are deleted.
- [ ] Snippets with `visibility: internal` (or no visibility field) are hidden from non-admin callers.
- [ ] Snippets with `visibility: public` are visible to all callers.
- [ ] Admin callers (role lookup from `caller_session_id`) see all snippets regardless of visibility.
- [ ] All existing `test_context_selector.py` tests pass unchanged.

## Constraints

- Global docs are only published by TeleClaude. No collision handling needed for cross-project IDs because project-scoped IDs are namespaced by project name.
- The manifest file must be writable by any project running `telec sync` (no locking needed; last-write-wins is acceptable for a small file).
- Phase 0 must be a single file read (no scanning at query time).
- Default visibility is `internal` (safe by default). Only explicitly marked `public` snippets are visible to restricted roles.
- Role resolution: `caller_session_id` → session lookup → `user_role` field. If no session or role found, default to `admin` (preserves current behavior for existing sessions).

## Risks

- Large number of projects could make the phase 1 index noisy. Mitigated by: phase 0 exists precisely to let the agent select which projects to load.
- Stale manifest entries for deleted projects. Mitigated by: phase 0 can skip entries whose `index` path no longer exists.
- Existing snippets without `visibility` field default to `internal`, which may surprise cross-project consumers. Mitigated by: batch-add `visibility: public` to intended public snippets during rollout.
