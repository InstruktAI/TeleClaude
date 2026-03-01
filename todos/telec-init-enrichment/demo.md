# Demo: telec-init-enrichment

## Validation

```bash
# Pre-check: create a sample project to test against
mkdir /tmp/demo-project && cd /tmp/demo-project
git init && echo '{"name":"demo","version":"1.0.0"}' > package.json
echo 'console.log("hello")' > index.js
mkdir -p src/routes && echo 'export default function Home() { return "hi" }' > src/routes/index.tsx
git add -A && git commit -m "initial"
```

```bash
# Run telec init with enrichment on the sample project
cd /tmp/demo-project && telec init
```

```bash
# Verify doc snippets were generated
telec docs index --baseline-only 2>/dev/null
ls docs/project/init/
```

```bash
# Verify snippets pass validation
telec sync --validate-only
```

```bash
# Verify snippet content is project-specific (not generic templates)
telec docs get project/init/architecture
```

```bash
# Verify re-init is idempotent — edit a snippet, re-run, verify edit preserved
echo "# Human addition" >> docs/project/init/architecture.md
telec init
grep "Human addition" docs/project/init/architecture.md
```

```bash
# Cleanup
rm -rf /tmp/demo-project
```

## Guided Presentation

### Step 1: The Problem — Cold Start

Start with a fresh project that has code but no AI-readable documentation.

**Do:** Show the project structure. Run `telec docs index` — it returns nothing
project-specific. The AI has no context.

**Observe:** The gap between "code exists" and "AI understands the code."

### Step 2: Run Enriched Init

**Do:** Run `telec init` on the project. The command does its usual plumbing (hooks,
watchers), then prompts: "Analyze project and generate documentation? [Y/n]"

**Observe:** Accept. An analysis session starts. The AI reads the codebase, identifies
patterns, and generates doc snippets. Progress is visible in the terminal.

### Step 3: Inspect Generated Documentation

**Do:** Run `telec docs index`. Show the new snippets: architecture, conventions,
dependencies, entry points, testing, build/deploy.

**Observe:** Each snippet ID follows the `project/init/*` namespace. Run
`telec docs get project/init/architecture` — the content is specific to THIS project,
not boilerplate. It names actual files, patterns, and frameworks found in the code.

### Step 4: Future Sessions Start Informed

**Do:** Start a new AI session on this project. Ask it about the architecture.

**Observe:** The AI loads the generated snippets via `telec docs index` + `telec docs get`
and immediately understands the project structure. No discovery phase needed.

### Step 5: Re-init Preserves Human Work

**Do:** Edit one of the generated snippets — add a section about a convention the AI
missed. Run `telec init` again.

**Observe:** The human-added section is preserved. Auto-generated sections are refreshed
with current analysis. The merge is visible in the git diff.

### Why It Matters

`telec init` is the seed. Before enrichment, it was plumbing. After enrichment, it's
the moment a project becomes part of the intelligence layer. Every future interaction —
every build, review, fix, conversation — benefits from the context that was bootstrapped
here.
