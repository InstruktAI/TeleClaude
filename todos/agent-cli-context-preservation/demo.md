# Demo: agent-cli-context-preservation

## Validation

The delivery combines a module rename, a Codex compaction prompt deployment, and context-preservation markers on distributed markdown outputs. This demo validates all three end-to-end.

## Guided Presentation

### 1. Verify the module rename

The `teleclaude.install.install_hooks` module is now `teleclaude.install.configure_agent_cli`. All three configurator functions remain accessible.

```bash
# Confirm the module is importable and provides the expected API
.venv/bin/python -c "
from teleclaude.install.configure_agent_cli import (
    configure_claude,
    configure_codex,
    configure_gemini,
)
print('✓ All configurator functions are accessible from the renamed module')
"
```

### 2. Verify the shell wrapper was inlined

The thin wrapper `bin/init/setup_agent_hooks.sh` no longer exists, and `bin/init.sh` invokes the Python entry point directly.

```bash
# Confirm the old wrapper script is gone
if [ ! -f bin/init/setup_agent_hooks.sh ]; then
  echo "✓ Old shell wrapper (bin/init/setup_agent_hooks.sh) is absent"
else
  echo "✗ Old wrapper still exists"
  exit 1
fi

# Confirm bin/init.sh invokes the renamed Python entry point
if grep -q "configure_agent_cli.py" bin/init.sh; then
  echo "✓ bin/init.sh invokes the renamed Python entry point"
else
  echo "✗ bin/init.sh does not reference configure_agent_cli.py"
  exit 1
fi
```

### 3. Verify the compaction prompt is repo-owned

A compaction prompt source file exists under the install settings area, ready to be deployed by the configurator.

```bash
# Confirm the compaction prompt file exists in the repo
PROMPT_FILE="teleclaude/install/settings/CODEX.compaction.md"
if [ -f "$PROMPT_FILE" ]; then
  echo "✓ Repo-owned compaction prompt exists at $PROMPT_FILE"

  # Verify it instructs Codex to preserve context markers
  if grep -q "TELECLAUDE_CONTEXT_PRESERVATION" "$PROMPT_FILE"; then
    echo "✓ Compaction prompt includes context-preservation instructions"
  else
    echo "✗ Compaction prompt does not mention context markers"
    exit 1
  fi
else
  echo "✗ Compaction prompt not found at $PROMPT_FILE"
  exit 1
fi
```

### 4. Verify the Codex settings override is configured

The `settings/codex.json` registers the compaction prompt for deployment.

```bash
# Confirm the Codex settings override includes the compaction prompt key
CODEX_SETTINGS="teleclaude/install/settings/codex.json"
if grep -q "experimental_compact_prompt_file" "$CODEX_SETTINGS"; then
  echo "✓ Codex settings override includes experimental_compact_prompt_file"

  # Verify the value points to the correct filename
  if grep -q "CODEX.compaction.md" "$CODEX_SETTINGS"; then
    echo "✓ Compaction prompt filename is correctly referenced"
  else
    echo "✗ Compaction prompt filename is not referenced correctly"
    exit 1
  fi
else
  echo "✗ experimental_compact_prompt_file not found in Codex settings"
  exit 1
fi
```

### 5. Verify context preservation markers are applied

The distribution pipeline wraps markdown outputs with the context-preservation markers.

```bash
uv run python - <<'PY'
import frontmatter

from scripts.distribute import (
    CONTEXT_PRESERVATION_END,
    CONTEXT_PRESERVATION_START,
    dump_frontmatter,
)

post = frontmatter.loads("---\nname: demo-check\ndescription: Validate markers.\n---\nBody.\n")
output = dump_frontmatter(post)

assert CONTEXT_PRESERVATION_START in output
assert CONTEXT_PRESERVATION_END in output

print("✓ Markdown serializer output contains context preservation markers")
PY
```

### 6. Verify prototype files are gone

The temporary project-local `.codex/` files that were superseded by the repo-managed path are removed.

```bash
# Confirm prototype files do not exist in the repo
if [ ! -f ".codex/config.toml" ] && [ ! -f ".codex/CODEX.compaction.md" ]; then
  echo "✓ Prototype .codex files are absent from the repository"
else
  echo "✗ Prototype files still exist:"
  [ -f ".codex/config.toml" ] && echo "  - .codex/config.toml"
  [ -f ".codex/CODEX.compaction.md" ] && echo "  - .codex/CODEX.compaction.md"
  exit 1
fi
```

### 7. Verify all references are updated

All internal imports, call-sites, and documentation reference the new module name.

```bash
# Confirm old module references are absent
if ! grep -r "from teleclaude.install import install_hooks" --include="*.py" --exclude-dir=".git" . 2>/dev/null; then
  echo "✓ Old install_hooks imports have been removed"
else
  echo "✗ Old install_hooks imports still exist"
  exit 1
fi

# Confirm guardrails.py references the new module path
if grep -q "configure_agent_cli.py" tools/lint/guardrails.py; then
  echo "✓ guardrails.py references the new module path"
else
  echo "✗ guardrails.py not updated"
  exit 1
fi
```

### 8. Verify tests pass

All expected-failure markers are removed and the test suite is green.

```bash
# Run the configurator tests
.venv/bin/python -m pytest tests/unit/install/test_configure_agent_cli.py -v --tb=short
TEST_EXIT=$?

# Run the distribution tests
.venv/bin/python -m pytest tests/unit/scripts/test_distribute.py -v --tb=short
DIST_EXIT=$?

if [ $TEST_EXIT -eq 0 ] && [ $DIST_EXIT -eq 0 ]; then
  echo "✓ All tests pass"
else
  echo "✗ Test failures detected"
  exit 1
fi
```

## Success Criteria

All verification blocks execute without error. The delivery is complete when:

1. ✓ Module rename is functional and all imports are updated
2. ✓ Shell wrapper is inlined and old script is removed
3. ✓ Compaction prompt exists in repo and is configured for deployment
4. ✓ Distribution pipeline wraps markdown with context markers
5. ✓ Prototype files are absent
6. ✓ All test expectations pass
