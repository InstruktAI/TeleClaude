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
shared layer that owns no domain rule. Ownership follows domain meaning: the
context definitions above and the published contracts in the domain specs
decide whose rule a package expresses. Package contents, current placement, and
file proximity never establish ownership. A package whose implementation
contradicts its owner's meaning is misplaced code and a finding against that
code, never a reason to move ownership; when two domain specs list the same
implementation root, the context definitions above decide and the spec listing
that disagrees is corrected. A row marked `provisional` rests on a reading of
domain meaning that no domain spec has yet declared; a row marked `unassigned`
names a package no context has claimed, and its owner is a pending ownership
decision, never inferred from placement. Paths are relative to `teleclaude/`
unless stated; `frontend/` and repository-root directories are listed by name.

| Package | Owner | Basis | Status |
| --- | --- | --- | --- |
| `core/agent_coordinator`, `core/command_handlers`, `core/reminders`, `core/tmux_bridge`, `daemon_session.py`, `cli/tool_commands/sessions`, `hooks`, `session_scoping/_attribution`, `core/session_bootstrap.py`, `core/session_cleanup.py`, `core/session_coordinator.py`, `core/session_environment.py`, `core/session_launcher.py`, `core/session_listeners.py`, `core/session_output.py`, `core/session_start_messages.py`, `core/session_startup_message.py`, `core/session_status.py`, `core/session_title.py`, `core/session_utils.py`, `core/agent_dispatch.py`, `core/agent_parsers.py`, `core/agent_prompt_state.py`, `core/agent_readiness.py`, `core/agents.py`, `core/tmux_io.py`, `core/output_poller.py`, `core/polling_coordinator.py`, `core/activity_contract.py`, `core/status_contract.py`, `core/tool_activity.py`, `core/tool_access.py`, `core/control_delivery.py`, `core/injected_text.py`, `core/session_message_projection.py`, `types/commands.py`, `helpers/agent_cli.py` | agent_runtime | agent_runtime spec: live sessions, supervised agent processes, session-input execution, runtime lifecycle; the hook receiver reaches agent_runtime directly and the hook-reception feature spec names agent_runtime its conceptual owner while inventorying it under integration | declared |
| `core/codex_transcript.py`, `core/summarizer.py`, `services/summarizer_backends.py`, `core/user_turn_reflection.py`, `core/user_reflection_observation.py`, `core/relay_context.py`, `core/lifecycle.py`, `core/voice_assignment.py`, `core/voice_message_handler.py`, `core/voice_recovery.py` | agent_runtime | reading of domain meaning: agent transcript parsing, summaries, and user-turn reflection are runtime observations of a live session; no domain spec names them | provisional |
| `adapters`, `core/inbound`, `core/delivery`, `events/delivery`, `core/adapter_client`, `transport`, `core/conversation_delivery.py`, `core/conversation_delivery_settlement.py`, `core/conversation_bundle_delivery.py`, `core/conversation_messages.py`, `core/conversation_segments.py`, `core/inbound_queue.py`, `core/inbound_types.py`, `core/inbound_errors.py`, `core/hook_outbox_handlers.py`, `core/hook_outbox_queue.py`, `core/integration_bridge.py`, `core/file_handler.py`, `core/adapter_errors.py`, `services/telegram.py`, `services/whatsapp.py`, `core/origins.py`, `core/parsers.py`, `core/metadata.py`, `core/feedback.py`, `core/error_feedback.py`, `core/person_messaging.py` | integration | integration spec: external-provider and process-boundary transport, normalization, translation; conversation delivery and settlement carry other contexts' messages without owning their semantics | declared |
| `core/command_dispatch.py`, `core/command_mapper.py`, `core/command_registry.py`, `core/command_service.py` | integration | reading of domain meaning: the command surface translates adapter and CLI commands into typed requests for their owning contexts; the registry and mapper are translation, the rules they invoke belong to their owners | provisional |
| `session_identity.py`, `commit_identity.py`, `api/auth.py`, `cli/telec/handlers/auth_cmds.py`, `invite.py`, `core/identity.py`, `core/operation_caller_identity.py`, `core/shell_identity.py` | identity | identity spec: caller resolution, authentication evidence, authorization identity | declared |
| `core/next_machine`, `core/todos_db`, `core/integration`, `services/work`, `todo_artifacts.py`, `todo_scaffold.py`, `git.py`, `git_lock.py`, `core/todo.py`, `core/todo_tree.py`, `core/todo_dependency_warnings.py`, `core/todos_db_path.py`, `core/dirty_path_owners.py`, `core/project_state.py`, `types/todos.py`, `types/lifecycle.py` | workflow | the workflow definition above: todos, artifacts, lifecycle decisions, dependency ordering, and code-integration workflow; the integration spec's listing of `core/integration` among its roots is corrected in the same change | declared |
| `core/operations`, `core/operation_progress.py`, `core/task_registry.py`, `quality`, `tools`, `session_scoping/_git`, `session_scoping/_workspace`, `session_scoping/_api`, `session_scoping/_extractors`, `session_scoping/_types.py` | workflow | reading of domain meaning: durable operations, task registry, quality gates, build tooling, and dirty-path custodianship serve delivery and integration decisions; no domain spec names them | provisional |
| `config`, `runtime/config.py`, `core/config_watcher.py` | config | config spec: file-backed v1 configuration and its watching | declared |
| `context_selector.py`, `docs_index.py`, `docs_reconcile.py`, `doc_body.py`, `required_reads.py`, `snippet_roots.py`, `snippet_validation.py`, `sync.py`, `third_party_index.py`, `global_skills.py`, `resource_validation`, `project_setup`, `install`, `core/blueprint`, `codegen`, `company_setup`, `content_scaffold.py`, `repository docs`, `repository agents`, `repository templates`, `repository manifests` | context | context spec: documentation, agent assets, their distribution (`install/` is named there as distribution code), context selection; the blueprint is knowledge about the code | declared |
| `memory` | memory | memory spec | declared |
| `mirrors`, `utils/transcript`, `history` | session_mirrors | session_mirrors spec: transcript-derived historical search | declared |
| `core/reconciliation`, `deployment`, `runtime/binaries.py`, `runtime/environment.py`, `entrypoints/macos_setup.py` | reconciliation | reconciliation spec: comparing declared installation capabilities with observed machine state and driving convergence | declared |
| `cli/tui`, `cli/telec`, `cli/tool_commands`, `cli/*.py`, `frontend`, `output_projection`, `api_models.py`, `api_server.py`, `codegen/pydantic_to_typescript.py` | presentation | the presentation definition above: ephemeral client projection and rendering policy over facts other contexts publish; the TUI, CLI, and web frontend are its hosting surfaces | declared |
| `api` | mixed, per route | `api/**` hosts HTTP routes for many contexts: each route is presentation's adapter, and the rule it invokes belongs to the publishing context (workflow for todo mutation, agent_runtime for sessions and MCP runtime, identity for auth); no route may implement a rule of its own | declared as hosting; per-route ownership recorded here, not in the router |
| `core/db`, `core/migrations`, `core/cache.py`, `core/dates.py`, `core/protocols.py`, `core/redis_utils.py`, `core/system_stats.py`, `core/event_bus.py`, `core/event_guard.py`, `core/events.py`, `events/catalog.py`, `events/db.py`, `events/domain_config.py`, `events/domain_handlers.py`, `events/domain_pipeline.py`, `events/domain_seeds.py`, `events/cartridges`, `events/schemas`, `events/signal`, `services/protocols`, `services/schemas`, `types/*.py (except `commands.py`, `todos.py`, `lifecycle.py`)`, `utils`, `logging_config.py`, `paths.py`, `constants.py`, `daemon.py`, `daemon_event_platform.py`, `daemon_hook_outbox.py`, `observability`, `helpers (except `agent_cli.py`)`, `mlx_utils.py`, `logs` | shared layer, no owner | neutral infrastructure: storage engine, bus mechanics, host process, utilities; carries no domain rule, and a rule found inside one of these is misplaced code | declared as layer |
| `core/models`, `core/db_models.py` | mixed, unresolved | `core/models` and `core/db_models.py` define session, adapter, reminder, memory, link, delivery, and operation state in one place; each model belongs to the context whose state it is, and the split is a pending ownership decision recorded per model, not a shared layer | unresolved |
| `channels`, `cron`, `services/process_janitor`, `services/project_catalog`, `services/project_jobs`, `services/maintenance_service.py`, `services/monitoring_service.py`, `services/log_bug_hunter_service.py`, `services/log_bug_hunter_suppressions.py`, `services/discord.py`, `services/email.py`, `tagging`, `mcp`, `events/domains`, `entrypoints/send_telegram.py`, `entrypoints/youtube_sync_subscriptions.py`, `chiptunes`, `tts`, `stt`, `capabilities.py`, `checkpoint_model.py`, `domains.py`, `project_manifest.py`, `project_root.py`, `shell_path_parser.py`, `slug.py`, `session_fields.py`, `services/surface.py` | unassigned | no context in this map claims them: jobs and channels, MCP, business-domain event pipelines, the chiptunes player (which persists favorites and so is not presentation's ephemeral projection), and assorted top-level modules; each awaits an ownership decision | unassigned |

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
