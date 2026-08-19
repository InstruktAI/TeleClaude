---
description: Onboard a new agent CLI harness as a first-class agent runtime — the facts to establish before writing code, every surface that must be touched, the traps that cost the most, and what "working" means.
visibility: internal
activation_trigger: Use when adding a new agent CLI (a vendor harness) as a first-class runtime, or when auditing an existing runtime for surfaces its onboarding missed.
---

# Onboard an Agent Harness — Procedure

## Required reads

- @docs/project/spec/domain/agent_runtime.md
- @docs/project/spec/domain/config.md
- @docs/project/spec/feature/config/agents-inventory-requirement.md

## Goal

Add a vendor agent CLI as a first-class agent runtime: launchable, readable,
checkpointable, searchable, and attributable — with no surface left holding a
stale agent count.

## Preconditions

- The decision to adopt the harness is the human's and has been made.
- The vendor CLI is installed on the machine and can be launched by hand.
- A session of that harness has been driven manually at least once, so its
  transcript, prompt, and hook behavior can be observed rather than guessed.

## Discipline

The failure this procedure guards against is **partial onboarding that looks
complete**. A new runtime reaches "it works" after the launch path and the hook
adapter land — the agent starts, answers, and stops. Everything downstream of
that (identity, transcript, scoping, search, distribution, UI arithmetic) fails
_silently_ and raises nothing: a duplicate dispatch falls through to the Claude
parser, a codegen literal quietly stops emitting a type, a status widget renders
three badges because three is baked into a style list. The registry is
not one list — it is roughly thirty independent places that each decided
separately how many agents exist, and the only defense is to walk them all and
prove each one. Treat "the agent is talking to me" as the midpoint of the work,
never the end of it.

## Steps

### 0. Earn the runtime

Confirm the harness is being adopted as a _runtime_ — something sessions launch,
that persists transcripts, and that TeleClaude drives — and not merely a model
reachable through an existing runtime. A model behind an existing CLI is a
`mode_chains` entry, not an onboarding.

### 1. Phase 0 — establish the facts before writing code

Answer every question below from **observation of a real session**, not from
vendor documentation and not from analogy to an already-onboarded harness. Each
one maps to a decision later steps depend on; an unanswered question becomes a
defect discovered live.

**Install and resolution**

1. Install channel and package name; where the binary lands. An npm-global
   install lands outside the launchd/systemd service PATH — see step 3.
2. Binary name versus agent key (they differ: key `gemini` → binary `agy`,
   key `deepseek` → binary `dsh`).

**Launch**

3. Launch shape: interactive TUI whose pane receives typed input, or one-shot
   taking the prompt as a launch argument (`prompt_at_launch`).
4. Profile or workspace concept, if any — and **who owns creating one**. If the
   vendor's plugin command auto-initializes a missing profile, the installer
   must guard on existence rather than call it.
5. How a model is selected: a CLI flag, a config file, or a per-launch overlay.
   A harness with no model flag needs a generated patch (`model_via_launch_patch`).
6. Sandbox/permission posture for the `default` and `restricted` profiles.
7. Resume and continue grammar (`resume_template`, `continue_template`).

**Readiness and input**

8. The idle prompt marker — the exact glyph, verified from a pane capture, not
   assumed from what it looks like in a terminal.
9. The input region's geometry: where the live input ends. A bordered composer
   needs an extraction rule or status text below the border reads as user input.
10. Terminal behavior: does the TUI self-clamp color under `$TMUX`, and what is
    its escape hatch? Does it need a locale?

**Persistence and identity**

11. Session root, file pattern, and compression.
12. **Session id shape — and which artifacts under the session root are not
    sessions.** Subagents, delegations, and forks live under the same root
    wearing the same shape. Find the discriminator field. A vendor's own id
    type is rarely a UUID even when most of its values look like one.
13. How the working directory is recovered from a transcript.

**Transcript**

14. The event vocabulary and its mapping onto the shared entry shape
    (`user` / `assistant` / `tool_use` / `tool_result`).
15. Whether entries carry a usable wall-clock timestamp, and in what unit.
16. Harness-injected user-shaped entries (runtime context blocks, checkpoint
    condensations, hook feedback) that must not count as real user turns.

**Hooks**

17. Does a hook system exist at all; its event names, payload shape, and stdout
    protocol.
18. Whether hook commands run sandboxed by default and how to opt out.
19. How a hook handler is packaged and where it lives — and whether it belongs
    in this repository at all. It usually does not: a vendor plugin authored at
    the harness's own plugin location is installed from there, so the repository
    carries only the installer wiring, never a vendored copy.

Record the answers. They are the input to every step below, and they are what
the next onboarding will want to diff against.

### 2. Registry and identity

The agent key is declared in more than one enum. Missing one produces a runtime
`ValueError` on a path that may not run until much later.

| Surface                                                            | What to add                                                                                                                                                                                |
| ------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `teleclaude/constants.py` → `AGENT_PROTOCOL`                       | The full launch contract: session paths, patterns, profiles, `mode_chains`, resume/continue templates, the `prompt_at_launch` / `model_via_launch_patch` / `restricted_sandbox_mode` flags |
| `teleclaude/constants.py` → `GIT_AUTHOR_IDENTITIES`                | Commit author identity for the agent                                                                                                                                                       |
| `teleclaude/core/agents.py` → `AgentName`                          | The canonical enum, plus `_PROMPT_MARKERS_BY_AGENT` and `_DISCORD_PRESENTATIONS_BY_AGENT`                                                                                                  |
| `teleclaude/helpers/agent_types.py` → `AgentName`                  | **The second enum.** It is a separate declaration and does not inherit from the first                                                                                                      |
| `teleclaude/hooks/receiver_args.py` → `RECEIVER_AGENT_CHOICES`     | Receiver `--agent` accepted values                                                                                                                                                         |
| `templates/config.yml`                                             | The `agents.<key>.enabled` entry                                                                                                                                                           |
| `docs/project/spec/feature/config/agents-inventory-requirement.md` | The known-agent set is contract; its scenarios name the allowed keys                                                                                                                       |

### 3. Launch path

1. `teleclaude/runtime/binaries.py` — binary resolution, and on macOS the
   launcher-bundle path.
2. `src/Launcher/build.sh` — add a launcher target so macOS TCC permissions
   attach to a stable signed identity. Bake fixed binary candidates at build
   time when the binary lives somewhere the service PATH does not reach.
3. `teleclaude/project_setup/macos_setup.py` — register the launcher bundle.
4. **PATH guarantees.** The daemon pane PATH is a best-effort capture of the
   user shell with a fallback to the service environment. If the binary lives in
   a directory that fallback lacks, pin it in both places: the agent-shell rc
   tree (`teleclaude/install/shell/{zshenv,bashenv,profile}`, kept
   byte-identical) and the generated service units
   (`bin/init/install_services.sh`).
5. Terminal hints belong in the agent-shell rc tree, not in the tmux env path —
   one source of truth reaching every pane regardless of host shell.
6. `teleclaude/core/command_handlers/_agent.py` — per-launch patch rendering,
   when the harness selects its model that way. Generate into the session
   tmpdir, pass by path, discard with the session; never a static file.

### 4. Readiness and input

1. `_PROMPT_MARKERS_BY_AGENT` — the verified idle glyph.
2. `teleclaude/core/agent_readiness.py` — the readiness profile. A pane-based
   TUI uses marker-line readiness; do not leave a comment claiming a headless
   posture the runtime does not have.
3. `teleclaude/core/agent_prompt_state.py` — a live-region extractor when the
   composer has a border or renders status lines beneath the input.
4. `teleclaude/core/tmux_bridge/_keys.py` — per-agent input escaping, if the
   harness mishandles any character.

### 5. Hooks

1. `teleclaude/hooks/adapters/<agent>.py` — the adapter: `agent_name`,
   `mint_events`, `supports_hook_checkpoint`, `checkpoint_response_kind`,
   payload normalization, and the checkpoint/additional-context response
   serializers.
2. `teleclaude/hooks/adapters/__init__.py` — register it in `_ADAPTERS`.
3. `teleclaude/core/events.py` → `HOOK_EVENT_MAP` — map every vendor event name,
   including the ones deliberately mapped to `None`.
4. **Mint set.** Unmapped stops must mint a headless session rather than drop.
   Every adapter mints `agent_session_start` and `agent_stop`; a new adapter
   that omits them loses events from manually started sessions.
5. Installer wiring: a `configure_<agent>` in its own
   `teleclaude/install/<agent>_hooks_install.py`, called from
   `configure_agent_cli.py`. Idempotent, preserving pre-existing user hooks.
6. Declare the unsandboxed opt-in if the receiver writes outside the workspace —
   it writes to the state dir and the outbox DB, so it does.

### 6. Transcript

Every entry here is a place a missing branch degrades silently.

1. `teleclaude/utils/transcript/_iterators.py` — the entry iterator, normalizing
   the vendor vocabulary to the shared shape, carrying timestamps, and handling
   compression. Register it in `_get_entries_for_agent`.
2. **Search for duplicate dispatches of the same decision.** `_get_entries_for_agent`
   is the canonical per-agent iterator switch, and it is not the only one. A
   second switch that lacks the new agent falls through to the Claude iterator
   and produces plausible, wrong output rather than an error.
3. `teleclaude/utils/transcript/_extraction.py` — the parser registry.
4. `teleclaude/utils/transcript/_rendering.py` — a markdown parser plus its
   `AGENT_TRANSCRIPT_PARSERS` entry, so transcript views do not hit the
   unknown-agent fallback.
5. `teleclaude/utils/transcript_discovery.py` — discovery, session-id
   extraction, and project recovery. **Skip the non-session artifacts** found in
   Phase 0 question 12 before their ids reach the identity invariant.
6. `teleclaude/utils/transcript/_user_turns.py` and
   `teleclaude/core/injected_text.py` — classify harness-injected user-shaped
   entries so they do not register as real user turns.
7. `teleclaude/session_scoping/_extractors/<agent>.py` plus its `__init__.py`
   registration — write/edit and shell-mutator paths from the normalized tool
   timeline.
8. `teleclaude/history/search.py` — include the agent in the all-agents list.

### 7. Surfaces

1. `teleclaude/cli/tui/theme.py` — palette entries for both appearance modes,
   and the known-agents set.
2. `teleclaude/cli/tui/animation_colors.py` — palette registration.
3. `teleclaude/cli/tui/widgets/telec_footer.py`, `widgets/modals.py`,
   `widgets/_status_controls.py` — **the arithmetic changes with the count.**
   Badge spacing, click-target offsets, and style lists written for N agents
   break at N+1. Derive from the enabled-agents list rather than a literal.
4. `teleclaude/api_models.py` — the DTO literals.
5. `teleclaude/codegen/pydantic_to_typescript.py` → `_LITERAL_ALIAS_VALUES` —
   the alias must match the DTO literal exactly. When it drifts, codegen stops
   emitting the named type and inlines the union instead, which reads as a
   cosmetic diff and silently strips a type the frontend imports.
6. `frontend/lib/api/types.ts`, `frontend/lib/theme/tokens.ts` — frontend agent
   unions and color tokens.
7. `teleclaude/cli/telec/surface_types.py`, `cli/tool_commands/sessions.py`,
   `cli/tool_commands/infra.py` — help text and error strings that enumerate
   agents. These are read by agents as well as humans, so a stale list is a
   stale contract.
8. `teleclaude/adapters/telegram/command_handlers.py` — the per-agent command,
   if the harness should be startable that way.

### 8. Artifacts and distribution

1. `agents/<AGENT>.addendum.md` — failure-mode corrections specific to this
   harness, and nothing else. Keep it to what _this_ agent gets wrong that
   others do not.
2. `scripts/distribute.py` — the agent's entry in the deploy map (check dir,
   `dist/` destinations, deploy destinations), the expansion predicate, and a
   skill-transform function matching the harness's `SKILL.md` shape.

### 9. Operations and role trust

1. `bin/install.sh` — install, configure, and the enabled/default-agent
   bookkeeping (its per-agent parameters are positional; adding one touches
   several lines).
2. `bin/setup-runner.sh` — the auth preflight check.
3. `teleclaude/helpers/agent_cli.py` → `_ONESHOT_SPEC` — the structured
   one-shot invocation used by summarizer and extraction paths. **Decide
   explicitly**: either add the entry, or record that the harness cannot serve
   one-shot structured calls. Silence here reads as an oversight later.
4. `teleclaude/core/agent_dispatch.py` — the lifecycle role orders. A runtime
   absent from these tuples can never be auto-dispatched to a workflow role.
   Whether the new harness is trusted for roles, and which, is **the human's
   decision** — carry it to them rather than defaulting either way.

### 10. Verification

The checkpoint obligations (`restart`, `log-check`) carry verification for the
code. Beyond them, prove each of these against a live session before calling the
onboarding done:

- A session starts, reaches its idle prompt, and receives a typed prompt.
- A stop checkpoint blocks the turn and the reason reaches the agent.
- A manually started session's hooks mint a headless session rather than drop.
- The mirror worker reconciles the transcript with `failed=0`, and
  `telec history search --agent <key>` returns a match.
- Session scoping attributes file mutations from the transcript.
- A commit from the session carries the agent's author identity.
- The TUI renders correctly at the new agent count, in both appearance modes.

## Outputs

- The harness is launchable, checkpointable, searchable, and attributable.
- A feature spec under `docs/project/spec/feature/agent_runtime/` carrying the
  runtime's contract as Gherkin scenarios.
- An addendum under `agents/` carrying its failure modes.
- The Phase 0 answers, recorded where the next onboarding can read them.

## Recovery

- **Agent key rejected at launch:** a registry surface in step 2 is missing the
  key — most often the second `AgentName` enum in `teleclaude/helpers/`.
- **Transcript output looks like another agent's:** a duplicate per-agent
  dispatch is falling through to the Claude iterator (step 6.2).
- **Reconciliation fails for one transcript every pass:** an artifact under the
  session root is not a session (step 6.5). The failure is per-transcript and
  contained; the cost is a repeating error, not an outage.
- **Hooks stop arriving with no error:** hook delivery fails silently. Check the
  harness's own hook log and confirm the handler is active in the profile the
  session actually launched, which may not be the profile it was installed into.
- **Colors wrong only inside a pane:** the TUI is self-clamping under `$TMUX`.
  Set its escape hatch in the agent-shell rc tree (step 3.5).
- **A UI widget renders the wrong number of agents:** a literal count or a
  hardcoded style list in step 7.3.

## See Also

- docs/project/spec/feature/agent_runtime/deepseek-harness-integration.md — the
  worked example this procedure was extracted from.
- docs/project/procedure/add-adapter.md — the adapter counterpart; adapters are
  transports, agent runtimes are launched processes.
