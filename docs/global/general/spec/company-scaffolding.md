---
description: 'Schema contract for company onboarding output: discovery-to-taxonomy mapping, snippet ID conventions, file placement, inbox processing, and merge rules for re-onboarding.'
visibility: 'public'
---

# Company Scaffolding — Spec

## Required reads

- @~/.teleclaude/docs/software-development/spec/init-scaffolding.md

## What it is

The schema contract between the `telec companies onboard` analysis session and
the company enrichment writer. Defines how organizational material is processed
into durable company doc snippets, how snippet IDs are structured, where files
land, and how re-onboarding merges without destroying human edits.

This spec is the company-scoped counterpart to the init scaffolding spec. The
taxonomy, merge rules, and validation contract are shared; the differences are
scope, storage location, and input surface.

## Canonical fields

### Storage Layout

```
~/.teleclaude/companies/{slug}/
  meta.yaml                         # company metadata and onboard history
  inbox/                            # input material (git-tracked)
  docs/                             # generated doc snippets
    principle/
    concept/
    policy/
    procedure/
    design/
    spec/
```

The `inbox/` directory is a git repository initialized by the onboard command.
This enables `git diff` for smart re-processing on subsequent onboard runs.

### Discovery-to-Taxonomy Mapping

Organizational material maps to taxonomy types. The analysis session decides
which snippets to produce based on what it finds — this mapping is guidance,
not a fixed checklist.

| Source Material                                      | Taxonomy Type | Snippet ID Pattern         |
| ---------------------------------------------------- | ------------- | -------------------------- |
| Company values, engineering principles, culture docs | `principle`   | `company/principle/{slug}` |
| Org structure, team topology, domain model, products | `concept`     | `company/concept/{slug}`   |
| HR policies, security standards, compliance rules    | `policy`      | `company/policy/{slug}`    |
| Onboarding flows, deployment SOPs, incident response | `procedure`   | `company/procedure/{slug}` |
| System architecture, infrastructure topology         | `design`      | `company/design/{slug}`    |
| API contracts, data schemas, service inventory       | `spec`        | `company/spec/{slug}`      |

### Snippet ID Conventions

Generated snippet IDs follow the pattern `company/{taxonomy}/{slug}` where:

- `{taxonomy}` is one of: `principle`, `concept`, `policy`, `procedure`, `design`, `spec`.
- `{slug}` is a lowercase kebab-case name derived from the content topic.
- IDs must be unique within the company scope.

Reserved snippet IDs (standard set, used as applicable):

```
company/concept/organization
company/concept/domain-model
company/concept/team-topology
company/policy/security
company/policy/coding-standards
company/procedure/onboarding
company/procedure/incident-response
company/design/architecture
company/spec/service-inventory
```

### Frontmatter Template

Every generated snippet authors only schema-permitted frontmatter:

```yaml
---
description: '{concise description}'
---
```

Classification (`id`, `type`, `scope`, `domain`) is **path-derived** by the index
build from the snippet's location under the company docs tree — never authored,
per the current snippet-authoring schema. Company membership is keyed by the
company folder in the snippet's path (`companies/<slug>/docs/<taxonomy>/...`),
which is what lets the context selector filter by project membership; there is
**no** authored `company` frontmatter field. `description` is the only required
authored field; `visibility` is optional. No `generated_by`/`generated_at` fields
are authored — they are not part of the snippet-authoring schema.

### Inbox Processing

The inbox is a git-tracked directory where humans dump organizational material
in any format the AI can read (markdown, PDF, plain text).

**Processing flow:**

1. On first onboard: `git init` the inbox, process all files, commit.
2. On re-onboard: `git diff HEAD` identifies new and modified files.
3. Each file is tracked by SHA in `meta.yaml` under `processed_files`.
4. Files with unchanged SHA are skipped (even if renamed or moved).
5. New files are added to the digest. Modified files trigger reprocessing
   of affected snippets.
6. Removed files do not remove generated knowledge — snippets persist.

**Bookkeeping in meta.yaml:**

```yaml
company_name: 'Acme Corp'
slug: 'acme'
created_at: '2024-01-15T10:30:00Z'
last_onboarded_at: '2024-03-20T14:00:00Z'
onboard_count: 3
processed_files:
  - path: 'handbook.pdf'
    sha256: 'abc123...'
    processed_at: '2024-01-15T10:30:00Z'
    snippets_produced:
      - company/policy/security
      - company/procedure/onboarding
  - path: 'architecture-overview.md'
    sha256: 'def456...'
    processed_at: '2024-03-20T14:00:00Z'
    snippets_produced:
      - company/design/architecture
snippets_generated:
  - company/concept/organization
  - company/policy/security
  - company/procedure/onboarding
  - company/design/architecture
snippets_preserved: []
```

### Merge Rules for Re-onboarding

The same merge rules as init scaffolding apply:

1. Identify existing snippets by their path under the company docs tree (recorded in `meta.yaml`); there is no authored `generated_by` field.
1. Human-authored sections after `<!-- human -->` survive.
1. Changed-file-only writes (preserve timestamps for unchanged content).
1. No duplication — update by ID.
1. New snippets are additive.
1. Removed snippets are preserved.

Additionally for re-onboarding:

7. **SHA-based skip.** Files with unchanged SHA since last processing are
   not re-analyzed, even if renamed or moved within the inbox.
8. **Diff-based reprocessing.** Modified files are reprocessed using
   `git diff` to identify what changed, enabling targeted snippet updates
   rather than full regeneration.

### Validation Contract

The enrichment writer validates all output before persistence:

- Snippet IDs must match the pattern `company/{taxonomy}/{slug}`.
- File destinations must resolve to paths under
  `~/.teleclaude/companies/{slug}/docs/`.
- Frontmatter authors only `description`; classification (`id`/`type`/`scope`/`domain`) is path-derived, never authored.
- Company membership is enforced by the snippet's path under `~/.teleclaude/companies/{slug}/docs/`, not a frontmatter field.

## Allowed values

- `company` slug: lowercase kebab-case (the company folder name; not an authored frontmatter field).
- `scope`/`type`/`id`: path-derived by the index build, never authored.

## Known caveats

- The inbox git repository is local-only — it is not pushed to any remote.
  Its sole purpose is enabling `git diff` for change detection.
- PDF and other binary formats produce SHA changes on any byte modification,
  even for non-content changes (metadata updates). The analysis session
  handles this gracefully by comparing semantic content, not file diffs.
- Company snippets are path-derived as `scope: global` but are filtered by the
  company folder in their path. They are global in reach but scoped in
  visibility to member projects.
