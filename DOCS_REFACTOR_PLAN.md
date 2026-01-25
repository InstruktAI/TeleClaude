# Documentation Refactor Plan

## Overview

Restructure documentation directories:

- `agents/docs` → `docs/global`
- `docs/*` → `docs/project`
- `docs-3rd` → `docs/third-party`

## Affected Components

### 1. Directory Structure

```
OLD:
├── agents/docs/          (global docs)
├── docs/                 (project docs)
└── docs-3rd/             (3rd party docs)

NEW:
└── docs/
    ├── global/           (was agents/docs/)
    ├── project/          (was docs/)
    └── third-party/      (was docs-3rd/)
```

### 2. Python Scripts

#### scripts/distribute.py

- Line 187: `master_docs_dir = os.path.join(agents_root, "docs")`
  → Change to: `master_docs_dir = os.path.join(project_root, "docs", "global")`
- Line 97: `if str(candidate).startswith("docs/"):`
  → Change to: `if str(candidate).startswith("docs/project/"):`
- Line 150: `if "path: agents/docs/" in line:`
  → Change to: `if "path: docs/global/" in line:`
- Line 151: `new_lines.append(line.replace("path: agents/docs/", "path: docs/"))`
  → Change to: `new_lines.append(line.replace("path: docs/global/", "path: docs/project/"))`

#### scripts/build_snippet_index.py

- Line 43: `return (f"@{root}/docs/", "@docs/")`
  → Check if this needs updating (depends on reference semantics)

#### scripts/sync_snippets.py

- Check for hardcoded paths

#### bin/lint/markdown.py

- Check for hardcoded paths

### 3. Project Setup Module

#### teleclaude/project_setup/gitattributes.py

```python
OLD:
FILTER_PATTERNS = [
    "docs/**/*.md filter=teleclaude-docs",
    "agents/docs/**/*.md filter=teleclaude-docs",
]

NEW:
FILTER_PATTERNS = [
    "docs/project/**/*.md filter=teleclaude-docs",
    "docs/global/**/*.md filter=teleclaude-docs",
]
```

#### teleclaude/project_setup/git_filters.py

- No changes needed (operates on content, not paths)

#### teleclaude/project_setup/hooks.py

- No changes needed (searches for patterns in any .md file)

#### teleclaude/project_setup/sync.py

- Check watcher paths if they reference specific directories

### 4. YAML Index Files

#### agents/docs/index.yaml

- All `path: docs/...` entries need to become `path: docs/global/...`
- Example: `path: docs/general/index.md` → `path: docs/global/general/index.md`

#### docs/index.yaml

- All `path: docs/...` entries need to become `path: docs/project/...`
- Example: `path: docs/architecture/cache-system.md` → `path: docs/project/architecture/cache-system.md`

### 5. Markdown Documentation References

#### Within docs (1041 markdown files)

- References like `@docs/...` need context-aware replacement:
  - In `docs/global/**/*.md`: `@docs/` → `@docs/global/`
  - In `docs/project/**/*.md`: `@docs/` → `@docs/project/`
- References like `@~/.teleclaude/docs/...` → `@~/.teleclaude/docs/global/...`

### 6. Symlink

#### scripts/distribute.py deployment

- Line 423: `deploy_docs_root = os.path.join(os.path.expanduser("~/.teleclaude"), "docs")`
- Line 427: `os.symlink(master_docs_dir, deploy_docs_root)`
- The symlink `~/.teleclaude/docs` will now point to `<repo>/docs/global`

### 7. Git Configuration

#### .gitattributes

```
OLD:
docs/**/*.md filter=teleclaude-docs
agents/docs/**/*.md filter=teleclaude-docs

NEW:
docs/project/**/*.md filter=teleclaude-docs
docs/global/**/*.md filter=teleclaude-docs
```

### 8. Launchd/Systemd Watchers

#### Files to watch

- Need to update watcher patterns from `agents/docs/**` to `docs/global/**`
- Need to update watcher patterns from `docs/**` to `docs/project/**`

## Migration Strategy

### Phase 1: Preparation (Dry Run)

1. Create backup/snapshot of current state
2. Run migration script with `--dry-run` flag
3. Generate report of all changes that would be made
4. Review report for correctness

### Phase 2: File System Migration

1. Create new directory structure
2. Move files:
   ```bash
   mkdir -p docs/global docs/project docs/third-party
   mv agents/docs/* docs/global/
   mv docs/* docs/project/ (excluding new dirs)
   mv docs-3rd/* docs/third-party/
   ```
3. Remove old directories

### Phase 3: Content Updates

1. Update YAML index files (path fields)
2. Update markdown `@docs/` references
3. Update markdown `@~/.teleclaude/docs/` references

### Phase 4: Code Updates

1. Update Python scripts
2. Update gitattributes patterns
3. Update project_setup module

### Phase 5: Rebuild & Deploy

1. Run `uv run scripts/build_snippet_index.py`
2. Run `uv run scripts/distribute.py --deploy`
3. Verify symlink points to correct location
4. Verify git filters still work
5. Verify watchers trigger correctly

### Phase 6: Verification

1. Run all tests
2. Verify MCP context retrieval works
3. Verify doc references resolve correctly
4. Check git status (should be clean after smudge/clean)

## Risks & Mitigation

### Risk 1: Breaking References

- **Mitigation**: Comprehensive regex-based find/replace with verification
- **Rollback**: Git reset hard (if committed) or restore from backup

### Risk 2: Symlink Breakage

- **Mitigation**: Test symlink creation in isolation first
- **Rollback**: Manually recreate old symlink

### Risk 3: Git Filter Confusion

- **Mitigation**: Update filters before moving files
- **Rollback**: Reset git config, restore .gitattributes

### Risk 4: Watcher Failures

- **Mitigation**: Test watcher reload after path changes
- **Rollback**: Restore old watcher config

## Rollback Plan

1. `git reset --hard` (if changes committed)
2. Restore from backup if files moved
3. Run `telec init` to restore old configuration
4. Restart daemon

## Testing Checklist

- [ ] Dry run completes without errors
- [ ] All file paths in migration report are valid
- [ ] No references left with old paths
- [ ] Git filters work (smudge/clean test)
- [ ] Symlink points to correct location
- [ ] MCP context retrieval returns correct snippets
- [ ] Unit tests pass
- [ ] Integration tests pass
- [ ] Manual verification of doc references in AI session
