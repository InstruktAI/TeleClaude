# Requirements: companies-onboard

## Goal

Enable company knowledge — org structure, policies, procedures, architecture — to automatically
flow into all projects linked to a company. A new company scope tier sits between global and project
scope: global in reach but filtered by project membership via a project-level config field.

## Scope

### In scope

- CLI command to onboard a new company by name (first onboard), creating the company directory
  and knowledge structure
- CLI command to re-onboard an existing company by slug, processing only new or changed material
- Company knowledge enrichment: converting company documents into structured doc snippets with
  correct scope, taxonomy, and company membership metadata
- Company snippet integration into context selection so projects with a matching company config
  see company docs in `telec docs index`
- Company index building included in `telec sync`
- Company snippet validation included in `telec sync`
- Analysis agent dispatch for processing company inbox documents

### Out of scope

- Company authentication or per-company access control
- Interactive config wizard integration for the company field (field is optional; users set it
  manually in `teleclaude.yml`)
- Cross-company snippet sharing

## Success Criteria

- [ ] `telec companies onboard <name>` successfully scaffolds the company directory structure
      on first onboard and dispatches an analysis session when inbox material is present
- [ ] `telec companies onboard --slug <slug>` on re-onboard processes only new or changed
      inbox files; unchanged files (same content) are skipped
- [ ] Projects with `company: <slug>` in `teleclaude.yml` see company snippets in
      `telec docs index`; projects without this config do not
- [ ] A project configured for company A does not see snippets from company B
- [ ] `telec sync --validate-only` validates company snippets and reports errors for invalid
      frontmatter or schema violations
- [ ] `telec sync` builds `index.yaml` for each company doc directory automatically
- [ ] All company snippets use `scope: global` and include a `company` frontmatter field
      matching the company slug

## Constraints

- The company slug must be lowercase kebab-case; invalid values must be rejected at config
  validation time
- Company docs must use the same taxonomy types, merge rules, and frontmatter validation as
  project enrichment
- Shared enrichment logic must not create cross-package coupling between the project setup
  and company setup packages
- Design documentation for this feature already exists at
  `docs/global/general/{concept,spec,procedure,design}/company-*.md` and must be followed
- The company knowledge layer design spec is the authoritative reference for snippet ID
  conventions, frontmatter requirements, and directory structure

## Risks

- Correct path semantics when indexing company docs outside any project directory tree
- Cross-company isolation: snippet membership filtering must be strict to prevent leakage
  in multi-company deployments
