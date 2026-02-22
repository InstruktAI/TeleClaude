# Demo: todo-remove-cli-option

## Validation

```bash
# Create a test todo
telec todo create test-demo-remove --after dep-a,dep-b

# Verify todo directory exists
test -d todos/test-demo-remove

# Verify roadmap entry exists
grep -q "test-demo-remove" todos/roadmap.yaml

# Remove the todo via CLI
telec todo remove test-demo-remove

# Verify directory is gone
! test -d todos/test-demo-remove

# Verify roadmap entry is gone
! grep -q "test-demo-remove" todos/roadmap.yaml
```

## Guided Presentation

This feature adds the ability to remove todos completely from the system, including:

1. **CLI Command**: `telec todo remove <slug>` deletes the todo directory and removes all references
2. **TUI Keybinding**: Press `R` in PreparationView to remove the currently selected todo
3. **Safety Guards**:
   - Confirmation dialog in TUI before deletion
   - Worktree guard prevents removal if `trees/{slug}/` exists
   - Dependency cleanup removes the slug from all `after` lists
4. **Complete Cleanup**: Removes from both `roadmap.yaml` and `icebox.yaml`, plus all dependency references

The validation above demonstrates the CLI flow - creating a todo, verifying it exists, removing it, and confirming complete cleanup.
