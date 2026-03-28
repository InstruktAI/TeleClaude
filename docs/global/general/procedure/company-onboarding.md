---
id: 'general/procedure/company-onboarding'
type: 'procedure'
domain: 'general'
scope: 'global'
description: 'Complete telec companies onboard flow — inbox processing, organizational analysis, company doc snippet generation, and project linking.'
---

# Company Onboarding — Procedure

## Required reads

- @~/.teleclaude/docs/general/spec/company-scaffolding.md

## Goal

Analyze organizational material dumped into a company inbox and produce durable,
company-scoped doc snippets that make the company's knowledge available to all
linked projects from the first session.

## Preconditions

- `telec` CLI is available and the daemon is running.
- At least one agent is enabled for session dispatch.
- For first onboard: a company name is provided.
- For re-onboard: the company already exists under `~/.teleclaude/companies/{slug}/`.
- Input material has been placed in the inbox directory (any readable format:
  markdown, PDF, plain text).

## Steps

### 1. Bootstrap company directory

On first onboard (`telec companies onboard <name>`):

- Derive slug from name (lowercase kebab-case).
- Create `~/.teleclaude/companies/{slug}/` with subdirectories:
  `inbox/`, `docs/`, and taxonomy directories under `docs/`.
- Initialize `inbox/` as a git repository for change tracking.
- Create `meta.yaml` with company name, slug, and creation timestamp.

On re-onboard:

- Verify the company directory exists.
- Read `meta.yaml` for processing history.

### 2. Detect input material

Scan the inbox directory for files to process:

- First onboard: all files in the inbox.
- Re-onboard: use `git diff HEAD` in the inbox repo to identify new and
  modified files. Compare SHA-256 of each file against `meta.yaml`
  `processed_files` to detect content changes even when files are renamed.
- Skip files with unchanged SHA.

### 3. Commit inbox state

After scanning, stage and commit any new or changed files in the inbox git
repository. This creates the baseline for the next re-onboard diff.

### 4. Dispatch analysis session

Launch a `/telec-company-analyze` session with:

- The company slug and inbox path as context.
- The list of new/changed files to process.
- The existing snippet inventory (for merge decisions).

The analysis session reads the input material and classifies it into the
taxonomy. It follows the company analysis procedure — a parallel of the
project analysis procedure adapted for organizational material.

### 5. Analysis session: orientation

The dispatched analysis session begins by:

- Reading the company's `meta.yaml` to understand prior onboard state.
- Listing all input files and their formats.
- Scanning file names and first pages to classify document types
  (policy document, org chart, handbook, architecture diagram, etc.).
- If existing snippets are present, loading them to understand what's
  already captured.

### 6. Analysis session: material classification

For each input file, determine its primary knowledge dimension:

- **Values, principles, culture** → `principle` snippets
- **Org structure, teams, products, domain language** → `concept` snippets
- **Policies, standards, compliance, rules** → `policy` snippets
- **Procedures, SOPs, workflows, runbooks** → `procedure` snippets
- **Architecture, infrastructure, system design** → `design` snippets
- **Contracts, schemas, inventories, specifications** → `spec` snippets

A single input file may contribute to multiple snippets across different
taxonomy types. The analysis session determines the natural boundaries.

### 7. Analysis session: snippet generation

Generate doc snippets following the company scaffolding spec:

- Use `company/{taxonomy}/{slug}` IDs.
- Include all required frontmatter fields including `company: {slug}`.
- Reference concrete findings from the input material — never generic templates.
- Apply merge rules for existing snippets (human edits survive).
- Validate all output before writing.

### 8. Analysis session: validation and bookkeeping

After snippet generation:

- Run `telec sync --validate-only` to confirm snippet validity.
- Update `meta.yaml` with:
  - `last_onboarded_at` timestamp.
  - Incremented `onboard_count`.
  - Updated `processed_files` with SHA and snippet associations.
  - Updated `snippets_generated` and `snippets_preserved` lists.

### 9. Link projects (manual step)

After onboarding, the user links projects to the company by adding
`company: {slug}` to each project's `teleclaude.yml`. This is a manual
configuration step — the onboard command does not modify project configs.

## Outputs

- Company directory bootstrapped under `~/.teleclaude/companies/{slug}/`.
- Inbox committed to local git for future diff tracking.
- Company doc snippets generated under `~/.teleclaude/companies/{slug}/docs/`.
- `meta.yaml` updated with processing history.
- Snippets discoverable via `telec docs index` when working in linked projects.

## Recovery

- `telec companies onboard` is idempotent. Re-running processes only changed
  material.
- If the analysis session fails mid-run, already-written snippets are valid.
  The session reports what was completed and what remains.
- If inbox git init fails, processing falls back to full analysis of all files
  (no diff optimization).
- The user can manually edit generated snippets — human edits are preserved
  on re-onboard via the `<!-- human -->` marker convention.
