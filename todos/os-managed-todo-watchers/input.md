# os-managed-todo-watchers — Input

Goal: move todo/worktree filesystem observation out of the daemon and into TeleClaude-installed OS watcher services, while keeping the daemon authoritative for invalidation, todo snapshot recompute, diffing, cache updates, and TUI/WebSocket fan-out.

Problem statement:
- The current daemon-owned TodoWatcher watches trusted project todos/ and trees/ roots and refreshes daemon cache on broad filesystem activity.
- Earlier investigation strongly suggested refresh amplification and watcher-thread pressure, not a classic runaway async task leak.
- Fresh logs after restart still show API loop-lag hang dumps with multiple watchdog/FSEvents threads, reinforcing the decision to remove daemon-owned watching.
- We want the same ownership model as docs sync: telec init installs a per-project watcher service managed by the operating system.

Architectural decision:
- The daemon must stop watching files directly.
- OS-managed watcher services observe project roots and report relevant path changes to the daemon over a dedicated internal API.
- The daemon remains the authority for all semantic effects: stale-preparation invalidation, todo recompute, digest comparison, cache update, and downstream refresh emission.
- Do not use the generic dynamic webhook subsystem for this. Use a dedicated internal route over the existing local Unix-socket API seam.

Platform strategy:
- macOS: telec init installs a launchd agent per project that runs a long-lived watcher process. The watcher observes the project root recursively and filters paths in-process.
- Linux: telec init installs a systemd --user service per project that runs a long-lived watcher process. The watcher observes the project root recursively and filters paths in-process.
- Do not use launchd WatchPaths or systemd.path for this feature. They are too coarse for deep recursive todo/worktree monitoring.
- Scope “Unix” to Linux for the first implementation. BSD/kqueue can remain out of scope unless explicitly required later.

Watcher responsibility split:
Watcher process:
- Watch exactly one root: the project root.
- Normalize events to project-relative POSIX-style paths.
- Evaluate both source and destination paths for move events.
- Ignore hidden/temp/editor noise.
- Match only the allowlisted todo/worktree paths.
- Batch and debounce matching paths into one notification per short window.
- Never perform todo recompute or TUI/WebSocket work locally.

Daemon internal route:
- Authenticate watcher requests.
- Verify project_root is trusted.
- Re-filter changed_paths server-side against the same allowlist.
- Invalidate stale preparation state if the changed paths affect that logic.
- Recompute the todo snapshot for the project once.
- Compare the new snapshot digest against the previous snapshot.
- Emit cache/WebSocket updates only when the digest changed.

Auth model:
- Do not use normal caller auth for watcher services; they do not have tmux or terminal login identity.
- Introduce a watcher-specific secret for the internal route.
- Secret is generated/stored by telec init and injected into the launchd/systemd service environment.
- Requests travel over the local Unix socket, not the public webhook surface.

Current repo-specific cleanup already completed:
- Remove the obsolete todos/icebox.md fallback from teleclaude/core/roadmap.py.
- Remove stale icebox.md validation logic from teleclaude/resource_validation/__init__.py.
- Update the stale spec mention in docs/project/spec/jobs/next-prepare.md.
- Commit made: chore: remove legacy icebox markdown fallback.

Path filtering contract to implement now:
- todos/*.yaml
- todos/*/*.md
- todos/*/*.yaml
- todos/_icebox/icebox.yaml
- todos/_icebox/*/*.md
- todos/_icebox/*/*.yaml
- trees/*/todos/*/*.md
- trees/*/todos/*/*.yaml

Additional relevant directory events:
- todos/<slug>
- todos/_icebox/<slug>
- trees/<slug>
- trees/<slug>/todos/<slug>
These create/delete/move events matter because worktree directory existence changes todo resolution.

Why this matcher is chosen:
- It keeps roadmap.yaml, delivered.yaml, and _icebox/icebox.yaml in scope now.
- It keeps _icebox included for future UI visibility or toggles.
- It keeps per-slug monitoring tight and avoids nested asset/reference noise for now.
- It is future-friendly: watcher scope can be broader than current semantic use, while daemon-side digest suppression prevents unnecessary churn.

Specific delivered.yaml guidance:
- Keep delivered.yaml in the watched surface now via todos/*.yaml.
- Even if delivered items are not currently included by default in assemble_roadmap(), delivered state is still part of todo lifecycle state and may affect staleness or pane computation later.
- This is a valid “watch now, act later” inclusion because downstream recompute is diff-gated.

Modules likely involved in implementation:
- teleclaude/project_setup/init_flow.py: install new todo watcher service during telec init.
- New project setup installer module next to teleclaude/project_setup/sync.py.
- New watcher command/module next to teleclaude/cli/watch.py, but not merged into docs sync logic.
- teleclaude/api_server.py: include new internal watcher route.
- New internal route module for watcher notifications.
- teleclaude/core/cache.py or adjacent cache/command handler logic: add project-level recompute with digest/no-op suppression.
- teleclaude/daemon.py: remove daemon startup of TodoWatcher after external watcher path is live.
- teleclaude/core/todo_watcher.py: retire after migration.

Rollout sequence:
1. Add internal watcher endpoint and daemon-side no-op suppression/digest comparison.
2. Add dedicated watcher command/process with batching and path filtering.
3. Add telec init installation for macOS and Linux watcher services.
4. Re-run telec init on projects as migration.
5. Remove daemon-owned TodoWatcher.
6. Re-evaluate TUI refresh volume only after watcher ownership is moved.

Tests expected before cutover:
- Path matcher accepts the allowlist above.
- Irrelevant files under trees/ do not trigger.
- todos/roadmap.yaml triggers.
- todos/delivered.yaml triggers.
- todos/_icebox/icebox.yaml triggers.
- trees/<slug>/todos/<slug>/state.yaml triggers.
- Move events inspect both old and new path.
- Matching changes that do not alter the assembled snapshot emit no refresh.
- Watcher route rejects missing/invalid secret.
- telec init installs exactly one todo watcher service per project on supported OSes.

Open implementation notes:
- The current watcher surface should stay intentionally tight on per-slug top-level md/yaml files; widen only when the UI actually consumes deeper nested todo assets.
- The daemon should never regain file-observation responsibility as fallback once the external path is in place.
