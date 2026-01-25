# Documentation Refactor - Manual Migration Checklist

## Status: Ready to Execute

## What We Already Did ✅

- [x] Renamed `build_snippet_index.py` → `sync_resources.py`
- [x] Added collision detection to `sync_resources.py`
- [x] Updated `distribute.py` to copy (not symlink) global docs
- [x] Updated `scripts/sync_resources.py` (collision detection + source_project tracking)
- [x] Updated `scripts/distribute.py` (\_merge_global_index function)
- [x] Updated `teleclaude/project_setup/gitattributes.py` (filter patterns)
- [x] Updated `scripts/sync_snippets.py` (import references)
- [x] Updated `teleclaude/context_index.py` (import references)
- [x] Updated test files (renamed test_build_snippet_index.py)
- [x] Updated `bin/sync_resources.py` and `teleclaude/tools/sync_resources.py`
- [x] Updated `teleclaude/project_setup/sync.py` (watcher command)

## Remaining Steps

### Step 1: Update Templates & Init Scripts

**File: `templates/teleclaude-docs-watch.path` (Line 7)**

```diff
- PathModified={{PROJECT_ROOT}}/agents/docs
+ PathModified={{PROJECT_ROOT}}/docs/global
```

**File: `bin/init/link_shared_scripts.sh` (Line 15)**

```diff
- ln -s "$INSTALL_DIR/agents/docs" "$docs_link"
+ ln -s "$INSTALL_DIR/docs/global" "$docs_link"
```

### Step 2: Move Directories

**Commands:**

```bash
cd /Users/Morriz/Documents/Workspace/InstruktAI/TeleClaude

# Create new structure
mkdir -p docs/global docs/project docs/third-party

# Move agents/docs to docs/global
mv agents/docs/* docs/global/
rmdir agents/docs

# Move docs-3rd to docs/third-party
mv docs-3rd/* docs/third-party/
rmdir docs-3rd

# Move current docs/* to docs/project/* (careful - exclude new subdirs)
for item in docs/*; do
  base=$(basename "$item")
  if [[ "$base" != "global" && "$base" != "project" && "$base" != "third-party" ]]; then
    mv "$item" docs/project/
  fi
done
```

### Step 3: Update YAML Index Path Fields

**File: `docs/global/index.yaml`**

- All `path: docs/...` → `path: docs/global/...`

**File: `docs/project/index.yaml`**

- All `path: docs/...` → `path: docs/project/...`

**Tool to help:**

```bash
# Global index
sed -i '' 's|path: docs/|path: docs/global/|g' docs/global/index.yaml

# Project index
sed -i '' 's|path: docs/|path: docs/project/|g' docs/project/index.yaml
```

### Step 4: Update Markdown @docs/ References

This happens automatically when we run sync_resources.py, but verify manually:

**In `docs/global/**/\*.md`:\*\*

- `@docs/` → `@docs/global/` (if not already)
- `@~/.teleclaude/docs/` → `@~/.teleclaude/docs/global/` (if not already)

**In `docs/project/**/\*.md`:\*\*

- `@docs/` → `@docs/project/` (if not already)

### Step 5: Update .gitattributes

**File: `.gitattributes`**

```diff
- docs/**/*.md filter=teleclaude-docs
- agents/docs/**/*.md filter=teleclaude-docs
+ docs/project/**/*.md filter=teleclaude-docs
+ docs/global/**/*.md filter=teleclaude-docs
```

### Step 6: Rebuild Indexes & Deploy

```bash
# Rebuild indexes (with new collision detection)
uv run scripts/sync_resources.py

# Deploy (will copy to ~/.teleclaude/docs/ instead of symlinking)
uv run scripts/distribute.py --deploy
```

### Step 7: Verification

```bash
# 1. Check git status
git status

# 2. Verify directory structure
ls -la docs/
ls -la docs/global/
ls -la docs/project/
ls -la docs/third-party/

# 3. Verify deployment
ls -la ~/.teleclaude/docs/
# Should NOT be a symlink, should be real directory with files

# 4. Verify indexes exist
ls -la docs/global/index.yaml
ls -la docs/project/index.yaml

# 5. Run tests
uv run pytest tests/unit/test_sync_resources.py -v

# 6. Test collision detection (should fail if we try duplicate ID)
# Create test file with duplicate ID and run sync_resources

# 7. Test git filters still work
git checkout HEAD -- docs/project/baseline/index.md
grep "@" docs/project/baseline/index.md | head -3
# Should show expanded paths in working copy
```

### Step 8: Update Documentation

**File: `README.md`**

- Line 147: Update path reference from `agents/docs/...` → `docs/global/...`
- Line 152: Update watcher description

### Step 9: Commit Changes

```bash
git add .
git status  # Review all changes

# Commit with detailed message
git commit -m "refactor(docs): restructure documentation directories

- Move agents/docs → docs/global (published to ~/.teleclaude/docs/)
- Move docs → docs/project (local project docs)
- Move docs-3rd → docs/third-party (3rd party research)
- Rename build_snippet_index.py → sync_resources.py
- Add collision detection for global doc IDs
- Change deployment from symlink to copy + merge
- Update all templates, scripts, and references

Breaking changes:
- Global docs now published via copy (not symlink)
- All projects can contribute to ~/.teleclaude/docs/
- ID collisions detected at build time with helpful errors

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

## Rollback Plan (if needed)

```bash
# If something goes wrong:
git reset --hard HEAD
rm -rf docs/global docs/project docs/third-party

# Restore original structure
git checkout HEAD -- agents/docs
git checkout HEAD -- docs
git checkout HEAD -- docs-3rd

# Remove deployment
rm -rf ~/.teleclaude/docs
```

## Expected Outcome

**Before:**

```
agents/docs/          → symlinked to ~/.teleclaude/docs/
docs/                 → project docs
docs-3rd/             → 3rd party docs
```

**After:**

```
docs/
  ├── global/         → copied to ~/.teleclaude/docs/ (merged from all projects)
  ├── project/        → project-specific docs (not published)
  └── third-party/    → 3rd party research (not published)
```

**Deployment:**

- Multiple projects can publish `docs/global/` to `~/.teleclaude/docs/`
- Collision detection prevents duplicate IDs
- Each snippet tracks `source_project` for ownership

## Notes

- Baseline docs in `docs/global/baseline/` are protected (collision check skips baseline)
- Git filters automatically expand `@~/.teleclaude/docs/` → `@/Users/Morriz/.teleclaude/docs/` in working copy
- Pre-commit hook blocks accidental hardcoded HOME paths
- Watcher auto-rebuilds on docs changes
