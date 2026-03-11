# Demo: prepare-phase-tiering

## Medium

CLI — all validation via `telec todo prepare` and `telec todo split` commands
with observable state.yaml changes.

## What the user observes

### Tier 1: Full pipeline (unchanged behavior)

A vague input goes through the complete prepare pipeline as before.

```bash
# Setup: create a todo with vague input
telec todo create tier1-demo
echo "Make the system faster somehow. Look into caching maybe?" > todos/tier1-demo/input.md

# Run prepare — expect full pipeline
telec todo prepare tier1-demo
# Output: dispatches next-prepare-discovery (tier 1 behavior)

# Verify tier assignment
grep "tier:" todos/tier1-demo/state.yaml
# Expected: tier: 1

# Verify no phases skipped
grep "skipped_phases" todos/tier1-demo/state.yaml
# Expected: skipped_phases: []
```

### Tier 2: Abbreviated pipeline (skip discovery)

A concrete, requirements-quality input skips discovery and goes straight
to plan drafting.

```bash
# Setup: create a todo with concrete, detailed input
telec todo create tier2-demo
cat > todos/tier2-demo/input.md << 'EOF'
# Add Redis TTL to session cache

## What
Add configurable TTL expiry to the session cache entries in
`teleclaude/core/cache/session_cache.py`. Currently entries never expire.

## Files
- `teleclaude/core/cache/session_cache.py` — add TTL parameter to set()
- `teleclaude/types/config.py` — add `session_cache_ttl` config key
- `config.sample.yml` — document the new key

## Success criteria
- [ ] `session_cache.set(key, value)` accepts optional `ttl_seconds` parameter
- [ ] Default TTL is 3600 seconds (1 hour)
- [ ] Config key `cache.session_ttl` overrides the default
- [ ] Expired entries return None on get()
EOF

# Run prepare — expect tier 2 (skip discovery)
telec todo prepare tier2-demo
# Output: tier assessed as 2, skips to plan drafting

# Verify state
grep "tier:" todos/tier2-demo/state.yaml
# Expected: tier: 2

grep "prepare_phase:" todos/tier2-demo/state.yaml
# Expected: prepare_phase: plan_drafting

# Verify skipped phases recorded
grep -A2 "skipped_phases" todos/tier2-demo/state.yaml
# Expected: entries for triangulation and requirements_review with reason tier_2

# Verify requirements promoted from input
test -s todos/tier2-demo/requirements.md && echo "requirements.md exists"
# Expected: requirements.md exists (promoted from input)

grep "verdict: approve" todos/tier2-demo/state.yaml
# Expected: requirements_review verdict is approve
```

### Tier 3: Direct build (skip all preparation)

A mechanical change skips the entire prepare pipeline.

```bash
# Setup: create a todo with zero-ambiguity mechanical input
telec todo create tier3-demo
cat > todos/tier3-demo/input.md << 'EOF'
Rename `get_session_cache` to `get_cache` in teleclaude/core/cache/__init__.py
and update all 3 import sites.
EOF

# Run prepare — expect tier 3 (immediate PREPARED)
telec todo prepare tier3-demo
# Output: PREPARED (no workers dispatched)

# Verify state
grep "tier:" todos/tier3-demo/state.yaml
# Expected: tier: 3

grep "prepare_phase:" todos/tier3-demo/state.yaml
# Expected: prepare_phase: prepared

# Verify all phases skipped
grep -c "skipped_at" todos/tier3-demo/state.yaml
# Expected: count > 0 (multiple phases skipped)
```

### Re-entry respects existing tier

```bash
# Call prepare again on the tier 2 item — should not re-assess
telec todo prepare tier2-demo
# Output: dispatches plan drafting (not re-assessment)

# Tier unchanged
grep "tier:" todos/tier2-demo/state.yaml
# Expected: tier: 2 (not re-assessed)
```

### Split inherits parent state

```bash
# Setup: create a parent that has approved requirements
# (simulate by writing requirements and setting state)
telec todo create split-demo-parent

# Split with approved requirements parent
telec todo split split-demo-parent --into split-child-a --into split-child-b

# Verify children inherited requirements
test -s todos/split-child-a/requirements.md && echo "child-a has requirements"
# Expected: child-a has requirements

grep "prepare_phase:" todos/split-child-a/state.yaml
# Expected: prepare_phase: plan_drafting (inherited from parent)

grep "tier:" todos/split-child-a/state.yaml
# Expected: tier: 2 (inherited approval means abbreviated pipeline)
```

### Backward compatibility

```bash
# Existing todo with no tier field in state.yaml
# (simulate by checking a legacy state.yaml)
grep "tier:" todos/some-legacy-todo/state.yaml
# Expected: tier: 0 (default, triggers assessment on next prepare call)

telec todo prepare some-legacy-todo
# Output: assesses tier, then routes accordingly (full pipeline if ambiguous)
```

## Cleanup

```bash
# Remove demo todos
telec todo remove tier1-demo
telec todo remove tier2-demo
telec todo remove tier3-demo
telec todo remove split-demo-parent
telec todo remove split-child-a
telec todo remove split-child-b
```
