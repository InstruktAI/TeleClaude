## Slug resolution

If `$ARGUMENTS` is empty, resolve the slug from context: worktree basename when cwd is under `trees/<slug>`, else `$TELEC_WORKING_SLUG`, else `telec todo show` against the current worktree, else `telec roadmap list --json` for the in-flight slug owned by this session. Never proceed with an empty slug — abort with one line telling the operator how to re-invoke.
