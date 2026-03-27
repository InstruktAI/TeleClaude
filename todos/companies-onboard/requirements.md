# Requirements: companies-onboard

## Goal

Enable company-scoped organizational knowledge to flow into all linked projects
automatically. When a project declares company membership, agents starting sessions
in that project receive the company's policies, procedures, principles, and domain
context alongside global and project documentation — filling the gap between
platform-wide knowledge and repository-specific knowledge.

This implements the company knowledge layer as defined in the governing
specifications listed below.

## Scope

### In scope

- CLI command for first onboard and re-onboard of company material
- Company directory bootstrapping per the company scaffolding spec
- Git-tracked inbox with change detection for incremental re-processing
- Company enrichment writer producing taxonomy-conformant doc snippets
- Context selection integration: company snippets visible in linked projects
- Index building for company doc directories
- Command artifact for the dispatched analysis session
- Sync integration: validation and index building for company docs
- Project configuration: company membership declaration
- Shared enrichment logic reused from existing project enrichment [inferred]

### Out of scope

- Multi-tenant authorization for company isolation (single-operator model is sufficient)
- Remote sync or push of company directories
- Automated project linking (user manually adds company config to projects)
- Company management commands beyond onboarding (list, delete, rename)

## Governing Specifications

The following documentation defines the contract for this work. The builder must
conform to these specs — they are the source of truth for storage layout, snippet
conventions, processing flow, and merge rules.

- `general/spec/company-scaffolding` — storage layout, snippet ID conventions,
  frontmatter template, inbox processing, merge rules, validation contract
- `general/design/company-knowledge-layer` — architecture, context selection
  hierarchy, multi-company isolation, failure modes
- `general/procedure/company-onboarding` — end-to-end onboarding flow
- `general/concept/company-knowledge` — scope hierarchy and taxonomy mapping
- `general/spec/snippet-authoring-schema` — snippet structure and section requirements

## Requirements

### R1: Project-company membership

Projects declare membership in a company through project configuration.

- **R1.1**: A project may belong to at most one company.
- **R1.2**: The membership value is a company slug: lowercase kebab-case, no special
  characters. Invalid formats are rejected at config validation time.
- **R1.3**: Membership is optional. Projects without a declared company load only
  global and project docs — the absence of a company is not an error.
- **R1.4**: The configuration surface (config wizard, sample config file) must expose
  this new field so users can discover and set it. [inferred — DoD gate: new
  configuration requires wizard and sample updates]

**Verification**: Config validation accepts valid slugs, rejects invalid formats,
and treats absence as no-company. Wizard and sample reflect the field.

### R2: Company bootstrapping

First onboard creates the company directory structure as defined in the company
scaffolding spec.

- **R2.1**: The onboard command accepts a company name and derives the slug
  (lowercase kebab-case).
- **R2.2**: The inbox directory is initialized as a git repository for change
  tracking, as specified in the scaffolding spec.
- **R2.3**: Meta tracking records company name, slug, creation timestamp, and
  processing history per the scaffolding spec's meta.yaml schema.
- **R2.4**: Slug collision detection: if a company directory already exists with a
  different company name in meta, onboard fails with a clear error suggesting a
  different name. [from design spec failure mode]
- **R2.5**: Taxonomy subdirectories are created under the docs directory per the
  scaffolding spec's storage layout.

**Verification**: Bootstrap produces the complete directory structure. Re-running
with the same name is idempotent. Colliding slugs from different names are rejected.

### R3: Inbox processing and change detection

The inbox provides incremental re-processing via git-based change detection.

- **R3.1**: First onboard processes all files in the inbox.
- **R3.2**: Re-onboard identifies new and modified files via git diff and SHA-256
  comparison against meta tracking, per the scaffolding spec's inbox processing rules.
- **R3.3**: Files with unchanged SHA are skipped, even if renamed or moved.
- **R3.4**: After scanning, inbox changes are committed to the local git repository
  to establish the baseline for the next re-onboard.
- **R3.5**: If no new or changed material is found, the command reports this and
  exits without dispatching analysis.
- **R3.6**: If inbox git initialization fails, processing falls back to full analysis
  of all files (no diff optimization). [inferred — from design spec recovery mode]

**Verification**: Re-onboard with unchanged inbox skips processing. Re-onboard with
modified files processes only the changed ones. Full fallback works when git is absent.

### R4: Analysis session dispatch

The onboard command dispatches an analysis session to process inbox material.

- **R4.1**: Analysis runs as a dispatched agent session (not inline in the CLI
  command), following the established session dispatch pattern.
- **R4.2**: The session receives the company slug, the list of files to process,
  and the existing snippet inventory as context.
- **R4.3**: The command reports the dispatched session ID so the user can follow
  progress.

**Verification**: Dispatch constructs a valid session with correct context. The
session ID is reported to the user.

### R5: Company enrichment and snippet generation

The analysis session produces company-scoped doc snippets conforming to the
scaffolding spec.

- **R5.1**: Generated snippets use the ID pattern, frontmatter template, and storage
  layout defined in the company scaffolding spec.
- **R5.2**: Snippet content references concrete findings from the input material —
  never generic templates or placeholder content.
- **R5.3**: Merge rules preserve human-edited sections (via the established
  human-marker convention) on re-onboard, per the scaffolding spec's merge rules.
- **R5.4**: The enrichment writer validates all output before persistence per the
  scaffolding spec's validation contract (ID pattern, storage path, required
  frontmatter fields, company field match).
- **R5.5**: Meta tracking is updated after generation with processed file SHAs,
  snippet associations, and generation timestamp per the scaffolding spec.

**Verification**: Generated snippets pass `telec sync --validate-only`. Human-marked
sections survive re-onboard. Meta tracking accurately reflects processing state.

### R6: Shared enrichment logic [inferred]

Merge, render, and validation logic used by both project and company enrichment
must be shared without duplication.

- **R6.1**: Existing project enrichment behavior must not change — this is a pure
  refactor with no behavioral modification.
- **R6.2**: Company enrichment reuses the same merge and human-edit preservation
  logic as project enrichment.

**Verification**: All existing project enrichment tests pass unchanged. Company
enrichment uses the shared logic and behaves consistently.

### R7: Context selection integration

Company snippets are discoverable in linked projects through the existing context
retrieval flow.

- **R7.1**: When a project declares company membership, `telec docs index` includes
  the company's snippets alongside global and project snippets.
- **R7.2**: Company snippets do not appear when a project has no company membership
  or declares a different company.
- **R7.3**: Precedence follows the hierarchy defined in the design spec:
  project > company > global.
- **R7.4**: Multi-company isolation: two companies on the same machine, two projects
  each linked to a different company — each project sees only its own company's
  snippets. Cross-company leakage is prevented by filtering on the company
  frontmatter field matching the project's declared company.
- **R7.5**: Missing company directory (project declares membership but the directory
  does not exist) produces a warning and proceeds without company docs — it does not
  fail the session. [from design spec failure mode]

**Verification**: `telec docs index` in linked projects shows company snippets. In
unlinked projects, they are absent. Cross-company leakage is tested with multiple
companies. Missing directory produces warning, not failure.

### R8: Index building

Company doc directories participate in index generation.

- **R8.1**: Each company's docs directory gets its own index, built during
  `telec sync`.
- **R8.2**: Empty company docs directories produce an empty index without errors.
- **R8.3**: Multiple companies each get independent indexes.

**Verification**: After onboarding, company index exists and is well-formed. Sync
completes without errors for empty, single, and multiple company directories.

### R9: Command artifact

A command artifact defines the analysis session's behavior.

- **R9.1**: The command artifact follows the established command artifact pattern and
  schema in the codebase.
- **R9.2**: It declares the governing company specs as required reads.
- **R9.3**: It executes the analysis flow defined in the company onboarding
  procedure: orientation, material classification, snippet generation, validation,
  and bookkeeping.

**Verification**: Artifact passes `telec sync --validate-only`. Dispatched sessions
follow the defined procedure.

### R10: Sync integration

Company directories participate in the sync validation and index building pipeline.

- **R10.1**: `telec sync` validates company doc snippets alongside global and project
  snippets.
- **R10.2**: `telec sync` triggers company index building.
- **R10.3**: Validation errors in company snippets are reported through the same
  error/warning mechanism as other validation errors.

**Verification**: `telec sync` reports errors for malformed company snippets and
succeeds for valid ones. Index building covers all companies.

### R11: CLI surface

A CLI namespace provides the onboard command.

- **R11.1**: First onboard accepts a company name as a positional argument.
- **R11.2**: Re-onboard accepts a company slug to identify the existing company.
- **R11.3**: Help text documents both modes with usage examples.
- **R11.4**: An optional project flag allows specifying the project directory,
  defaulting to the current working directory. [inferred — from input]

**Verification**: CLI parses both first-onboard and re-onboard forms correctly.
Help text is accurate and complete.

## Constraints

- The existing domain cartridge infrastructure uses a separate path from the company
  knowledge layer. The knowledge layer must not collide with or disrupt domain
  cartridge storage. [inferred — from codebase grounding: existing
  `~/.teleclaude/company` for domain cartridges is distinct from the knowledge
  layer's storage]
- Company snippets use `scope: global` with a company-identifying frontmatter field
  for filtering, as defined in the scaffolding spec. They are global in reach but
  scoped in visibility.
- The inbox git repository is local-only — no remote push. Its sole purpose is
  enabling change detection.
- Company knowledge is point-in-time, updated only on explicit re-onboard.
- Removed inbox files do not remove generated snippets — knowledge persists.

## Risks

- **Size**: This work spans configuration, CLI, bootstrapping, enrichment,
  context selection, index building, command artifact, and sync integration. The
  draft phase should evaluate whether splitting into sequential phases reduces
  session risk, applying the splitting heuristics from the Definition of Ready.
  The highly detailed input and established codebase patterns suggest a single
  coherent session may be viable, but the breadth is notable.
- **Enrichment extraction**: Extracting shared logic from existing project
  enrichment is a refactor that must not change existing behavior. Regression
  risk is mitigated by existing test coverage, but the builder must verify
  all existing enrichment tests pass after extraction.
