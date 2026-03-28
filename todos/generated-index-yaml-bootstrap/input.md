# generated-index-yaml-bootstrap — Input

Goal: stop committing generated index.yaml files anywhere in the repo and make bootstrap regenerate them reliably.

Plan:
1. Add one gitignore rule that ignores index.yaml in any location.
2. Untrack currently committed index.yaml files while keeping them generated locally by telec sync.
3. Update init/bootstrap so telec sync runs before any step that depends on generated indexes, especially before shared docs linking.
4. Remove sync repair logic that assumes docs/global/index.yaml exists in HEAD; generated indexes must be recovered by regeneration, not git restore.
5. Keep telec sync generating index.yaml files as local build artifacts.
6. Align watcher behavior with the generated-artifact rule for index.yaml files.
7. Update documentation/process language so index.yaml is treated as generated output, not authored source.
8. Add or update targeted tests covering bootstrap generation, sync recovery, and watcher ignore behavior.

Acceptance:
- Fresh install/init produces required local index.yaml files automatically.
- index.yaml files are no longer tracked by git.
- telec sync and watcher behavior remain stable.
- No workflow depends on restoring generated index.yaml from HEAD.
