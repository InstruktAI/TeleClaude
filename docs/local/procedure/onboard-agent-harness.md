---
description: Onboard a new agent CLI harness as a first-class agent runtime — the facts to establish before writing code, every surface that must be touched, the traps that cost the most, and what "working" means.
visibility: internal
activation_trigger: Use when adding a new agent CLI (a vendor harness) as a first-class runtime, or when auditing an existing runtime for surfaces its onboarding missed.
---

# Onboard an Agent Harness — Procedure

## Required reads

- @docs/local/spec/domain/agent_runtime.md
- @docs/local/spec/domain/config.md
- @docs/local/spec/feature/config/agents-inventory-requirement.md

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
adapter land — the agent starts, answers, and stops. The canonical agent entry
is the onboarding seam for identity, launch, readiness, attribution,
presentation, configuration, and dispatch. Typed and generated projections
carry that vocabulary to consumers; a hand-maintained second agent list is a
defect. Treat "the agent is talking to me" as the midpoint of the work, never
the end of it: transcript, scoping, search, distribution, and the real setup
path still require live verification.

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
4. Profile or workspace concept, if any.
5. How a model is selected: a CLI flag, a config file, or a per-launch overlay.
   A harness with no model flag needs a generated patch (`model_via_launch_patch`).
6. Sandbox/permission posture for the `default` and `restricted` profiles.
7. Resume and continue grammar (`resume_template`, `continue_template`).

**Readiness and input**

8. The idle prompt marker — the exact glyph, verified from a pane capture, not
   assumed from what it looks like in a terminal.
9. The composer's own markers, verified from a pane capture: the prompt glyph,
   the frame, border, or padding the CLI draws as part of the composer, where
   the CLI places the input cursor, and how an empty composer renders. These
   markers alone bound the live input; footers, status lines, hints, and labels
   outside them are never read.
   9a. The composer control contract: which leading characters of a pasted,
   submitted prompt start an interface mode or command (shell, slash commands,
   any other prefix the vendor documents), and which single neutralizing
   character placed before them makes the composer treat the prompt as
   ordinary text and still submit it on one discrete Enter. Verify each by
   pasting through the platform's own delivery path, including a control
   character preceded by leading whitespace; a keystroke observation or
   another runtime's answer does not transfer, because composers trim and strip
   different characters before deciding.
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
    (`user` / `assistant` / `pre_tool_use` / `tool_result`).
15. Whether entries carry a usable wall-clock timestamp, and in what unit.
16. Harness-injected user-shaped entries (runtime context blocks, checkpoint
    condensations, hook feedback) that must neither open an agent turn nor
    count as authored input.

**Hooks**

17. Does a hook system exist at all; its event names, payload shape, and stdout
    protocol. Per event, two independent capabilities, since an event may have
    either, both, or neither: whether its response reaches the model in the
    running turn and by which exact field, and whether it reports that the agent
    produced output or changed state. Note the invocation frequency of any event
    that fires repeatedly within one assistant message.
    17a. Payload fields that discriminate one lifecycle position from another — a
    counter, an idle flag — where the same native event fires at more than one
    point in a turn. Such an event maps internally as the pair of event name and
    payload predicate, never the name alone.
    17b. Whether the harness's own native subagents emit hooks into the same
    receiver, and the evidence that tells a subagent's events from the primary
    session's, observed from a real subagent run: a payload field where the
    harness provides one, otherwise a record the harness itself keeps for the
    subagent's conversation. Observe too which execution reports the turn's
    completion when a subagent outlives the conversation that invoked it. The
    harness keeps its native subagents in managed sessions, as the parallelism
    tool `general/principle/parallel-work` prescribes. Their events are
    recognized by that evidence and dropped before session resolution, as Codex
    subagent events are, and a turn completion the harness reports only on a
    subagent's hook reaches the invoking conversation's session as its own; the
    subagent invocation itself is never denied.
18. Whether hook commands run sandboxed by default and how to opt out.
19. How a hook handler is packaged and where it lives — and whether it belongs
    in this repository at all. It usually does not: a vendor plugin authored at
    the harness's own plugin location is installed from there, so the repository
    carries only the installer wiring, never a vendored copy.

Also establish compaction: the command that compacts the agent's context when
typed into its composer, and the native hook event, with its discriminating
payload, that reports that a compaction it was asked for completed. A harness
offering both declares compaction in its registry entry; one lacking either
declares none, and its conversation sessions are not idle-closed
(`local/projects/teleclaude/spec/feature/agent_runtime/conversation-continuity`).

Record the answers. They are the input to every step below, and they are what
the next onboarding will want to diff against.

### 2. Registry and identity

1. Add one complete entry to the canonical leaf agent registry. The entry owns
   the agent key, execution contract, attribution, readiness, composer control
   contract (Phase 0 question 9a), compaction (Phase 0), presentation, dispatch
   position, and launcher metadata.
2. Consume the registry's typed projections for backend validation, receiver
   arguments, history search, configuration inventory, and agent-specific
   runtime decisions. Do not introduce another enum, tuple, set, or map whose
   keys redefine the supported-agent vocabulary.
3. Regenerate the published API and frontend vocabulary from the canonical
   entry. A frontend declaration that shadows generated agent types, names, or
   palette data is a second registry and is removed.
4. Keep operational surfaces that cannot import the runtime registry derived
   from its generated outputs. A new runtime is not onboarded while installer,
   runner, launcher, or configuration templates can omit it silently.

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
2. `teleclaude/core/agent_readiness.py` — the readiness profile and complete
   composer observation. A pane-based TUI uses marker-line readiness, and its
   profile identifies the complete composer, and whether it is empty or
   occupied, from the composer's own markers alone, which also distinguish it
   from any other interactive screen. Readiness is assessed on settled
   activity, and no row outside the composer takes part in identifying it. Do
   not leave a comment claiming a headless posture the runtime does not have.

3. The composer control contract established in Phase 0 question 9a, declared
   on the canonical entry. The host-pane paste primitives carry no per-agent
   escaping, because relayed text is delivered as sent apart from the marks
   that contract declares
   (`local/projects/teleclaude/spec/feature/agent_runtime/session-input-delivery`).

### 5. Hooks

1. `teleclaude/hooks/adapters/<agent>.py` — the adapter: `agent_name`, payload
   normalization, and one `native_hook_specs` manifest. Each `NativeHookSpec`
   names the normalized event and only the TeleClaude capabilities the native
   boundary actually has: control delivery (with its exact provider channel)
   and/or headless-session minting.
2. `teleclaude/hooks/adapters/__init__.py` — register it in `_ADAPTERS`.
3. Declare only native events TeleClaude installs and consumes. Complete vendor
   vocabularies stay in consolidated third-party documentation; do not recreate
   them as `None` mappings or an installer cleanup catalog.
4. Implement `render_response(hook_event_name, intent) -> HookEmission` as the
   single provider-output boundary. It consumes the receiver's closed semantic
   intent and renders the exact wire shape allowed for that native event.
5. **Mint capability.** Session-start and stop boundaries must declare minting
   when they can be the first observable event from a manually started session;
   omitting the capability loses those events rather than adopting the session.
6. Installer wiring: a `configure_<agent>` in its own
   `teleclaude/install/<agent>_hooks_install.py`, called from
   `configure_agent_cli.py`. Idempotent, replacing identifiable TeleClaude
   receiver commands while preserving foreign and opaque provider-owned entries.
7. Declare the unsandboxed opt-in if the receiver writes outside the workspace —
   it writes to the state dir and the outbox DB, so it does.

### 6. Transcript

Every entry here is a place a missing branch degrades silently.

1. `teleclaude/utils/transcript/_iterators.py` — the entry iterator, normalizing
   the vendor vocabulary to the shared shape, carrying timestamps, and handling
   compression, plus the runtime's `TRANSCRIPT_READERS` record: display name,
   reader, tail limiter, and the checkpoint window normalizer when its transcript
   can be read from the tail. Every transcript load, render, and parse resolves
   the runtime through that record.
2. **Search for per-agent decisions outside the records.** A branch on the agent
   name that the records do not own falls through to another runtime's
   behavior and produces plausible, wrong output rather than an error. Route
   such a decision through the record instead of adding a branch.
3. `teleclaude/utils/transcript_discovery.py` — discovery, session-id
   extraction, and project recovery. **Skip the non-session artifacts** found in
   Phase 0 question 12 before their ids reach the identity invariant.
4. `teleclaude/utils/transcript/_user_turns.py` — the runtime's
   `RUNTIME_USER_VOCABULARY` record: its native entry markers, the complete
   texts it injects into a transcript position and at the prompt hook, and the
   spans it injects into mixed text. TeleClaude's own envelopes and the command
   loader are classified once for every runtime by
   `teleclaude/core/injected_text.py` and need no per-runtime entry.
5. `teleclaude/session_scoping/_extractors/<agent>.py` plus its `__init__.py`
   registration — write/edit and shell-mutator paths from the normalized tool
   timeline.
6. `teleclaude/history/search.py` — include the agent in the all-agents list.

### 7. Surfaces

8. Confirm the TUI consumes the canonical palette and supported-agent
   projections. Agent-count arithmetic derives from the enabled inventory.
9. Confirm the API code generator emits the named agent type, agent-name list,
   and cross-language presentation data from the canonical registry.
10. Remove frontend shadows of generated agent types, names, and palette data.
    Lists iterate the generated agent names; agent-specific icon maps are
    exhaustive over the generated union and carry no fallback that aliases an
    unknown agent to another runtime.
11. Confirm agent-facing CLI help and validation output renders the canonical
    vocabulary rather than maintaining prose lists.

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
- A feature spec under `docs/local/spec/feature/agent_runtime/` carrying the
  runtime's contract as Gherkin scenarios.
- An addendum under `agents/` carrying its failure modes.
- The Phase 0 answers, consolidated under `docs/third-party/<runtime>/` as that
  runtime's own documentation root, at parity with the runtimes already there.
  `hooks.md` is required: it carries the event vocabulary, payload shapes,
  per-event output contracts, and stdout protocol that later surfaces read. The
  remaining guides follow the shape the existing roots use; a guide the runtime
  has no surface for is omitted rather than filled with an empty section.

  Every fact is grounded in the installed runtime — the binary, its help
  surface, its configuration tree, and its own embedded documentation where it
  has one. A vendor README is a source, never a substitute; where the two
  disagree, the installed runtime governs. A fact that cannot be established is
  recorded as an explicit gap, never inferred from a runtime that looks
  similar.

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

- docs/local/spec/feature/agent_runtime/deepseek-harness-integration.md — the
  worked example this procedure was extracted from.
- ~/.teleclaude/docs/sdlc/principle/architecture-boundary-purity.md — why
  readiness rests on the composer's own markers, never on the presentation
  around it.

- docs/local/procedure/add-adapter.md — the adapter counterpart; adapters are
  transports, agent runtimes are launched processes.
