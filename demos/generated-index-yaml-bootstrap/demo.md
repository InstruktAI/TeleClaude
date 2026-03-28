# Demo: generated-index-yaml-bootstrap

## Validation

```bash
# R1: No index.yaml files tracked by git
test "$(git ls-files '**/index.yaml' | wc -l)" -eq 0
```

```bash
# R1: Gitignore covers index.yaml
git check-ignore docs/global/index.yaml
```

```bash
# R6: No git filter rules reference index.yaml
! grep -q 'index.yaml' .gitattributes
```

```bash
# R3: Sync repair function does not reference index.yaml in tracked files
! grep -q 'index.yaml' teleclaude/sync.py || \
  python3 -c "
import ast, sys
tree = ast.parse(open('teleclaude/sync.py').read())
for node in ast.walk(tree):
    if isinstance(node, ast.FunctionDef) and node.name == '_repair_broken_docs_links':
        src = ast.get_source_segment(open('teleclaude/sync.py').read(), node)
        if 'index.yaml' in src:
            print('FAIL: index.yaml still in _repair_broken_docs_links'); sys.exit(1)
print('OK: _repair_broken_docs_links does not reference index.yaml')
"
```

```bash
# R2/R5: telec sync produces index.yaml files and distributes them
uv run --quiet -m teleclaude.cli.telec sync --warn-only
test -f docs/global/index.yaml
test -f docs/project/index.yaml
test -f ~/.teleclaude/docs/index.yaml
```

```bash
# R7: No docs describe index.yaml as tracked or filtered
! grep -qi 'index.yaml' docs/project/spec/git-docs-filter.md
```

## Guided Presentation

### Step 1: Verify git exclusion

Show that no `index.yaml` files appear in the git index. Run `git ls-files '**/index.yaml'` —
expect empty output. Then show the gitignore rule with `git check-ignore -v docs/global/index.yaml`
to confirm the `**/index.yaml` pattern catches it.

**Why it matters:** This is the core change. Generated artifacts should never be committed.

### Step 2: Verify local generation still works

Run `telec sync --warn-only` and observe that `index.yaml` files are generated at each
snippet root (`docs/global/`, `docs/project/`, `docs/third-party/`). Check that
`~/.teleclaude/docs/index.yaml` also exists after distribution.

**Why it matters:** Proves the bootstrap path works on a codebase where `index.yaml` is
not in git — the normal state after this change.

### Step 3: Verify sync repair is clean

Open `teleclaude/sync.py` and show the `_repair_broken_docs_links` function. Point out
that only `docs/global/baseline.md` remains in `tracked_docs_files` — `index.yaml` is
gone because recovery is now regeneration, not git retrieval.

**Why it matters:** If the old git-HEAD recovery path remained, it would silently fail
(the file is no longer in git) and mask actual problems.

### Step 4: Verify git filter cleanup

Show `.gitattributes` — the `docs/*/index.yaml filter=teleclaude-docs` line is gone.
Show `docs/project/spec/git-docs-filter.md` — no index.yaml references remain.

**Why it matters:** Stale configuration creates false confidence and debugging confusion.

### Step 5: Run tests

Run `make test` and show all tests pass, including the new coverage for watcher exclusion,
sync repair, and bootstrap ordering.
