# Demo: companies-onboard

## Validation

<!-- Bash code blocks that prove the feature works. -->
<!-- Blocks are validated by `telec todo demo validate companies-onboard` (structural check) during build. -->
<!-- Execution (`telec todo demo run companies-onboard`) happens on main after merge. -->

### 1. Bootstrap a new company

```bash
# Create the company — should scaffold directory structure and report success
telec companies onboard "Demo Corp"
```

Expected: prints the company directory path (`~/.teleclaude/companies/demo-corp/`)
and dispatched session ID.

### 2. Verify directory structure

```bash
# Confirm all expected directories and meta.yaml exist
ls -la ~/.teleclaude/companies/demo-corp/
ls ~/.teleclaude/companies/demo-corp/docs/
cat ~/.teleclaude/companies/demo-corp/meta.yaml
```

Expected: `inbox/`, `docs/` with taxonomy subdirs, `meta.yaml` with
`company_name: Demo Corp`, `slug: demo-corp`, `created_at` timestamp.

### 3. Verify inbox is a git repo

```bash
git -C ~/.teleclaude/companies/demo-corp/inbox rev-parse --is-inside-work-tree
```

Expected: prints `true`.

### 4. Re-onboard with no changes

```bash
# Re-onboard should detect no new material
telec companies onboard --slug demo-corp
```

Expected: prints "No new material to process".

### 5. Context selection — company snippets visible in linked project

```bash
# After analysis session completes and project is linked (company: demo-corp in teleclaude.yml),
# company snippets should appear in docs index
telec docs index | grep "company/"
```

Expected: lists `company/` scoped snippet IDs from the generated company docs.

### 6. Context selection — isolation from unlinked projects

```bash
# In a project WITHOUT company config, company snippets should be absent
# (Run from a project that does not have company: demo-corp)
telec docs index | grep "company/" | wc -l
```

Expected: `0` — no company snippets leak into unlinked projects.

### 7. Sync validates company snippets

```bash
telec sync --validate-only
```

Expected: passes without errors for company docs.

## Guided Presentation

### Step 1: The problem

Company knowledge — policies, procedures, org structure, domain language — currently
has no durable home in TeleClaude. Every project session starts without organizational
context. Agents don't know about company coding standards, team topology, or compliance
requirements unless someone re-explains them every time.

### Step 2: Bootstrap a company

Run `telec companies onboard "Demo Corp"`. This creates the company directory under
`~/.teleclaude/companies/demo-corp/` with:

- `inbox/` — git-tracked directory where you dump organizational material
- `docs/` — where generated company knowledge snippets live (taxonomy structure)
- `meta.yaml` — tracks onboarding state, processed files, and snippet inventory

The inbox is initialized as a git repo for smart change detection on re-onboards.

### Step 3: Dump material and analyze

Place your company handbooks, policy documents, architecture overviews — anything
the AI should know about your organization — into the inbox directory. Then run
`telec companies onboard --slug demo-corp` again. The command detects new files,
commits the inbox state, and dispatches an analysis session.

The analysis session classifies material into the taxonomy (principle, concept,
policy, procedure, design, spec) and generates company-scoped doc snippets.

### Step 4: Link projects

Add `company: demo-corp` to any project's `teleclaude.yml`. From that moment, every
agent session in that project loads the company's knowledge alongside global and
project docs. Run `telec docs index` to confirm company snippets are visible.

### Step 5: Multi-company isolation

Each company has its own isolated directory. Snippets from one company never appear
in projects linked to a different company. The context selector filters by the
`company` frontmatter field matching the project's declared membership.

### Step 6: Re-onboard

When company material changes, re-run `telec companies onboard --slug demo-corp`.
Only new or modified files are re-processed (SHA-based skip). Human edits to generated
snippets survive via the `<!-- human -->` marker convention — same merge rules as
project enrichment.
