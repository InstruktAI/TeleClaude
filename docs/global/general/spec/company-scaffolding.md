---
description: 'Schema contract for company onboarding output: discovery-to-taxonomy mapping, snippet ID conventions, file placement, inbox processing, and merge rules for re-onboarding.'
visibility: 'public'
---

# Company Scaffolding — Spec

## Required reads

- @~/.teleclaude/docs/sdlc/spec/init-scaffolding.md

## What it is

<!-- planned-change:procedure-role-capability-composition -->

The schema contract between the `/companies-analyze` analysis session and
the company enrichment writer. Defines how organizational material is processed
into durable company doc snippets, how snippet IDs are structured, where files
land, and how re-onboarding merges without destroying human edits.
<!-- change:procedure-role-capability-composition -->

The schema contract between the `general/procedure/company-analysis` analysis session and
the company enrichment writer. Defines how organizational material is processed
into durable company doc snippets, how snippet IDs are structured, where files
land, and how re-onboarding merges without destroying human edits.
<!-- /planned-change:procedure-role-capability-composition -->

This spec is the company-scoped counterpart to the init scaffolding spec. The
taxonomy, merge rules, and validation contract are shared; the differences are
scope, storage location, and input surface.

## Canonical fields

### Storage Layout

```
~/.teleclaude/companies/{company}/
  teleclaude.yml                    # the company's declaration
  meta.yaml                         # company metadata and onboard history
  AGENTS.master.md                  # from the platform's company template
  inbox/                            # input material (git-tracked)
  docs/
    global/                         # what the company publishes
      <taxonomy>/…
    local/                          # generated doc snippets, never published
      baseline.md                   # local baseline manifests, created once
      baseline-progressive.md
      <taxonomy>/…
  help-desk/                        # when the company's help desk is enabled
```

The `inbox/` directory is a git repository initialized by the onboard command.
This enables `git diff` for smart re-processing on subsequent onboard runs.

`telec config company init` creates this home. The company's master and its
help desk's master are seeded from their templates while absent — by that init
and by the platform home's convergence at commit-boundary maintenance and
through `telec sync` — and then belong to the company, whose history records
them. The local baseline manifests are created once and then curated by the
company, and a taxonomy directory appears when its first snippet is written.

The analysis session writes every generated snippet into `docs/local/`.
`docs/global/` holds what the company deliberately publishes, including every
procedure that declares `subscriptions`; the analysis session never moves a
snippet there on its own. The half decides where a snippet is served from, never who may read it
(`general/policy/artifact-scope`).

### Discovery-to-Taxonomy Mapping

Organizational material maps to taxonomy types. The analysis session decides
which snippets to produce based on what it finds — this mapping is guidance,
not a fixed checklist.

| Source Material                                      | Taxonomy Type | Snippet ID Pattern                            |
| ---------------------------------------------------- | ------------- | --------------------------------------------- |
| Company values, engineering principles, culture docs | `principle`   | `local/companies/{company}/principle/{topic}` |
| Org structure, team topology, domain model, products | `concept`     | `local/companies/{company}/concept/{topic}`   |
| HR policies, security standards, compliance rules    | `policy`      | `local/companies/{company}/policy/{topic}`    |
| Onboarding flows, deployment SOPs, incident response | `procedure`   | `local/companies/{company}/procedure/{topic}` |
| System architecture, infrastructure topology         | `design`      | `local/companies/{company}/design/{topic}`    |
| API contracts, data schemas, service inventory       | `spec`        | `local/companies/{company}/spec/{topic}`      |

### Snippet ID Conventions

Generated snippet IDs follow the pattern `local/companies/{company}/{taxonomy}/{topic}` where:

- `{company}` is the company's declared slug.
- `{taxonomy}` is one of: `principle`, `concept`, `policy`, `procedure`, `design`, `spec`.
- `{topic}` is a lowercase kebab-case name derived from the content topic.
- IDs are derived from the snippet's path; a generated snippet lives in the local
  half, so its ID carries the `local/` prefix.

Reserved snippet IDs (standard set, used as applicable):

```
local/companies/{company}/concept/organization
local/companies/{company}/concept/domain-model
local/companies/{company}/concept/team-topology
local/companies/{company}/policy/security
local/companies/{company}/policy/coding-standards
local/companies/{company}/procedure/onboarding
local/companies/{company}/procedure/incident-response
local/companies/{company}/design/architecture
local/companies/{company}/spec/service-inventory
```

### Frontmatter Template

Every generated snippet authors only schema-permitted frontmatter:

```yaml
---
description: '{concise description}'
---
```

Classification (`id`, `type`, `scope`, `domain`) is **path-derived** by the index
build from the snippet's location under the company home — never authored,
per the current snippet-authoring schema. Company ownership is keyed by the
company folder in the snippet's path (`companies/<slug>/docs/{global,local}/<taxonomy>/...`),
which is what lets the context selector read the snippet at the caller's depth
on that company; there is **no** authored `company` frontmatter field. `description` is the only required
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
      - local/companies/acme/policy/security
      - local/companies/acme/procedure/onboarding
  - path: 'architecture-overview.md'
    sha256: 'def456...'
    processed_at: '2024-03-20T14:00:00Z'
    snippets_produced:
      - local/companies/acme/design/architecture
snippets_generated:
  - local/companies/acme/concept/organization
  - local/companies/acme/policy/security
  - local/companies/acme/procedure/onboarding
  - local/companies/acme/design/architecture
snippets_preserved: []
```

### Merge Rules for Re-onboarding

The same merge rules as init scaffolding apply:

1. Identify existing snippets by their identity (recorded in `meta.yaml`); there is no authored `generated_by` field.
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

- Snippet IDs must match the pattern `local/companies/{company}/{taxonomy}/{topic}`.
- File destinations must resolve to paths under
  `~/.teleclaude/companies/{company}/docs/local/`.
- Frontmatter authors only `description`; classification (`id`/`type`/`scope`/`domain`) is path-derived, never authored.
- Company ownership is enforced by the snippet's path under `~/.teleclaude/companies/{company}/docs/`, not a frontmatter field.

## Allowed values

- `company` slug: lowercase kebab-case (the company folder name; not an authored frontmatter field).
- `scope`/`type`/`id`: path-derived by the index build, never authored.

## Known caveats

- The inbox git repository is local-only — it is not pushed to any remote.
  Its sole purpose is enabling `git diff` for change detection.
- PDF and other binary formats produce SHA changes on any byte modification,
  even for non-content changes (metadata updates). The analysis session
  handles this gracefully by comparing semantic content, not file diffs.
- Company snippets are path-derived as `scope: company` in both halves. Members
  and platform admins read them in full from any location; everyone else reads
  their `visibility: public` snippets only, whichever half holds them.
