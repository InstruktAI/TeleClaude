---
visibility: internal
description: Frozen v1 map of practical ownership areas used to classify current feature contracts.
---

# Context Map — Spec

## What it is

The v1 repository is a distributed Python monolith. Its contexts are semantic
ownership and dependency boundaries even when several of them share one process
or database deployment. Every domain decision, behavior, invariant, state model,
and vocabulary term belongs to exactly one context. Feature work is classified
against that owner; cross-context behavior composes the owners' published
contracts and never creates shared ownership.

## Canonical fields

- `agent_runtime`: live sessions, supervised agent processes, session-input
  execution, and runtime lifecycle. It does not own provider transport,
  presentation, identity decisions, or workflow state.
- `context`: documentation, agent assets, deployment, and context selection.
- `identity`: caller resolution, authentication evidence, and authorization
  identity. It does not own provider parsing or the domain action authorized.
- `integration`: external-provider and process-boundary transport,
  normalization, and translation. It does not own session, workflow, identity,
  or presentation policy merely because it carries those contexts' messages.
- `memory`: durable preference observations and retrieval.
- `session_mirrors`: transcript-derived historical search.
- `workflow`: todos, artifacts, lifecycle decisions, dependency ordering, and
  code-integration workflow.
- `config`: file-backed v1 configuration.
- `reconciliation`: installation and fleet convergence behavior.
- `presentation`: the ephemeral display state of TeleClaude's own UI clients —
  the TUI, the CLI, and the web frontend: local projections, caches, and
  rendering policy over data other contexts publish. It owns no published
  facts, no persistence, and no other context's semantics; it never redefines,
  validates, defaults, or recovers a publishing context's rules. Its observable
  behavior is bound by the feature specs its clients realize.

### Package ownership

Every source package has exactly one owning context, declared here, or is a
shared layer that owns no domain rule. Ownership follows the contexts' own
declarations above and in their domain specs; where a package's contents
contradict a declaration, the contents decide and the row says so. A row marked
`provisional` rests on the package's contents alone; a row marked `unassigned`
names a package no context has claimed, and its owner is a pending ownership
decision, never inferred from placement. Paths are relative to `teleclaude/`
unless stated; `frontend/` and repository-root directories are listed by name.

| Package | Owner | Basis | Status |
| --- | --- | --- | --- |
| `core/agent_coordinator`, `core/command_handlers`, `core/reminders`, `core/tmux_bridge`, `daemon_session.py`, `cli/tool_commands/sessions` | agent_runtime | agent_runtime spec; live sessions, session-input execution, runtime lifecycle | declared |
| `session_scoping/_attribution` | agent_runtime | boundary contract above: the live-session attribution query | declared |
| `adapters/**`, `core/inbound`, `core/delivery`, `events/delivery`, `core/adapter_client`, `transport/**` | integration | integration spec; provider and process-boundary transport, normalization, translation | declared |
| `hooks/**` | integration | feature spec `integration/agent-cli-hook-reception`; overrides the agent_runtime spec's path mention | declared, conflict resolved by contents |
| `session_identity.py`, `commit_identity.py`, `api/auth.py`, `cli/telec/handlers/auth_cmds.py`, `invite.py` | identity | identity spec; caller resolution and authorization identity | declared |
| `core/next_machine`, `core/todos_db`, `core/integration`, `core/operations`, `services/work`, `todo_artifacts.py`, `todo_scaffold.py`, `git.py`, `git_lock.py`, `quality/` | workflow | workflow spec; todos, artifacts, lifecycle decisions, code-integration workflow and its quality gates | declared; `core/integration` conflict with the integration spec resolved by contents (state machine, lease, delivery fold) |
| `session_scoping/_git`, `session_scoping/_workspace`, `session_scoping/_api` | workflow | boundary contract above: coordination and custodianship over dirty paths | provisional |
| `config/`, `runtime/config.py` | config | config spec | declared |
| `context_selector.py`, `docs_index.py`, `docs_reconcile.py`, `doc_body.py`, `required_reads.py`, `snippet_roots.py`, `snippet_validation.py`, `sync.py`, `third_party_index.py`, `global_skills.py`, `resource_validation/`, `project_setup/`, `core/blueprint`, `codegen/`, `company_setup/`, repository `docs/`, `agents/`, `templates/`, `manifests/` | context | context spec; documentation, agent assets, deployment of context, context selection; the blueprint is knowledge about the code | declared; `core/blueprint`, `codegen`, `company_setup` provisional |
| `memory/**` | memory | memory spec | declared |
| `mirrors/`, `utils/transcript`, `history/` | session_mirrors | session_mirrors spec; transcript-derived history | declared; `history/` provisional |
| `core/reconciliation`, `deployment/`, `install/**`, `runtime/binaries.py`, `runtime/environment.py`, `entrypoints/macos_setup.py` | reconciliation | context map: installation and fleet convergence; overrides the context spec's `install/` mention | declared, conflict resolved by the map's definition |
| `cli/tui/**`, `cli/telec/**` (except auth handlers), `cli/*.py`, `frontend/`, `api/**` (except auth), `api_models.py`, `api_server.py`, `output_projection/`, `chiptunes/`, `tts/**`, `stt/**` | presentation | context map: TUI, CLI, and web frontend hosting surfaces; local projections and rendering policy | declared; `chiptunes`, `tts`, `stt` provisional as output and input modalities of the clients |
| `core/db`, `core/models`, `core/migrations`, `events/catalog.py`, `events/db.py`, `events/domain_*`, `events/cartridges`, `events/schemas`, `events/signal`, `services/protocols`, `services/schemas`, `types/`, `utils/` (except `transcript`), `logging_config.py`, `paths.py`, `constants.py`, `daemon.py`, `daemon_event_platform.py`, `daemon_hook_outbox.py`, `observability/`, `helpers/`, `mlx_utils.py` | shared layer, no owner | storage, bus, transport, host, and utility layers; each carries no domain rule of its own, and every rule found inside one is misplaced | declared as layer |
| `channels/`, `cron/`, `services/process_janitor`, `services/project_catalog`, `services/project_jobs`, `services/maintenance_service.py`, `services/monitoring_service.py`, `services/log_bug_hunter_*`, `services/discord.py`, `services/email.py`, `tagging/`, `mcp/`, `events/domains/**`, `entrypoints/send_telegram.py`, `entrypoints/youtube_sync_subscriptions.py`, `content_scaffold.py`, `capabilities.py`, `checkpoint_model.py`, `domains.py`, `project_manifest.py`, `project_root.py`, `shell_path_parser.py`, `slug.py`, `session_fields.py` | unassigned | no context in this map claims them; jobs, channels, MCP, and business-domain pipelines await an ownership decision | unassigned |

### Boundary contracts

- `integration` hands normalized session input to `agent_runtime` through the
  session-input delivery contract; it does not redefine runtime acceptance,
  queueing, or processing semantics.
- `integration` supplies authenticated caller signals to `identity`; identity
  owns their interpretation and returns the resolved principal.
- `workflow` requests session dispatch, observes session lifecycle, and consumes
  ephemeral dirty-path claimant evidence through `agent_runtime` contracts.
  `agent_runtime` owns the single-snapshot live-session attribution query;
  `workflow` owns coordination, custodianship, and resulting repository actions.
  Neither context implements the other's decisions or state transitions.
- `agent_runtime` publishes transcript and lifecycle facts consumed by
  `session_mirrors`; the mirror context never mutates live session truth.

<!-- planned:docs-tier-layering -->
- `context` resolves a caller's documentation reach from `identity`'s resolved
  person and resolved organizational membership, and from `config`'s project-tier
  declaration of an owning company. `identity` owns what those facts mean;
  `config` owns the declarations behind them; `context` owns only what a given
  set of relationships permits a caller to read, and never infers a relationship
  the resolved facts do not state.
<!-- /planned:docs-tier-layering -->
The daemon, handler, adapter, database, and background-worker labels are layers
or hosting mechanisms, not additional contexts. The TUI, the CLI, and the web
frontend are `presentation`'s hosting surfaces. Existing placement outside
these relationships is not precedent; the owning context and published contract
remain authoritative.

## See Also

- docs/project/adr/0069-vnext-authority-lives-in-separate-repository.md
