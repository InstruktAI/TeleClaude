# Demo: telec-init-enrichment

## Validation

```bash
# Pre-check: create a sample project to test against
mkdir /tmp/demo-project && cd /tmp/demo-project
git init
cat > package.json <<'EOF'
{"name":"demo-project","version":"1.0.0","scripts":{"test":"vitest"}}
EOF
mkdir -p src/routes
echo 'export default function Home() { return "hi" }' > src/routes/index.tsx
echo 'console.log("hello")' > index.js
git add -A && git commit -m "initial"
```

```bash
# Run telec init and accept enrichment
cd /tmp/demo-project && telec init
```

```bash
# Wait for the analysis session to complete (enrichment runs asynchronously).
# Poll until snippets appear or timeout after 120s.
timeout 120 bash -c 'until find /tmp/demo-project/docs/project -maxdepth 2 -name "*.md" 2>/dev/null | grep -q .; do sleep 3; done'
```

```bash
# Verify generated snippets land in the project taxonomy
find /tmp/demo-project/docs/project -maxdepth 2 -type f | sort
telec docs index
```

```bash
# Verify snippet retrieval is project-specific, not boilerplate
telec docs get project/design/architecture
telec docs get project/policy/conventions
telec docs get project/spec/dependencies
```

```bash
# Verify generated snippets pass validation and the project is registered locally
cd /tmp/demo-project && telec sync --validate-only
telec projects list | rg demo-project
```

```bash
# Verify re-init preserves human edits
# Record current analysis timestamp so we can detect when re-analysis completes
prev_analyzed=$(grep last_analyzed_at /tmp/demo-project/.telec-init-meta.yaml | cut -d: -f2- | tr -d ' ')
echo "# Human addition" >> /tmp/demo-project/docs/project/design/architecture.md
cd /tmp/demo-project && telec init
# Wait for re-analysis to complete (timestamp changes when enrichment finishes)
timeout 120 bash -c "until [ \"\$(grep last_analyzed_at /tmp/demo-project/.telec-init-meta.yaml | cut -d: -f2- | tr -d ' ')\" != \"$prev_analyzed\" ]; do sleep 3; done"
# Verify human edits survived the re-analysis
rg "Human addition" /tmp/demo-project/docs/project/design/architecture.md
```

```bash
# Cleanup
rm -rf /tmp/demo-project
```

## Guided Presentation

### Step 1: The Problem — Cold Start

Start with a fresh project that has code but no AI-readable project snippets.

**Do:** Show the project structure. Run `telec docs index` and point out that there
is no project-specific architecture, conventions, or dependency context yet.

**Observe:** The gap between "code exists" and "AI understands the code."

### Step 2: Run Enriched Init

**Do:** Run `telec init`. The command performs its existing plumbing and then offers
optional enrichment.

**Observe:** Accept the enrichment prompt. An analysis session starts, reads the repo,
and reports completion when snippet generation and validation finish.

### Step 3: Inspect Generated Documentation

**Do:** Run `telec docs index` and `telec docs get project/design/architecture`.

**Observe:** The generated snippets live under `docs/project/design/`,
`docs/project/policy/`, and `docs/project/spec/`. The content names real files,
frameworks, entry points, config files, and conventions from this repo.

### Step 4: Confirm Local TeleClaude Integration

**Do:** Run `telec projects list`.

**Observe:** The repo appears in the local project catalog and points at
`docs/project/index.yaml`, so other TeleClaude surfaces can discover it.

### Step 5: Re-init Preserves Human Work

**Do:** Append a short human-authored note to `docs/project/design/architecture.md`
and run `telec init` again.

**Observe:** The human note remains while the generated sections refresh. The git diff
shows an in-place merge, not duplicated snippets.

### Why It Matters

`telec init` stops being plumbing-only. It becomes the moment a raw repo gains
durable, queryable project context for future AI sessions.
