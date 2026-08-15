---
description: Comparative research on Prime Agent, Cordis, and DeepSeek Harness as harness, runtime, and extensible UI building blocks.
---

# Prime Agent, Cordis, and DeepSeek Harness

## Research question

Can any of these projects provide the experience layer above TeleClaude's future harness adapters, while TeleClaude retains workflow, routing, identity, and availability authority?

## Relationship and boundaries

| Project          | Actual boundary                                                                        | Stable integration surface                                                                                       | Current maturity                                                           |
| ---------------- | -------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------- |
| Prime Agent      | Pi-derived coding and research harness with its own agent runtime                      | JSONL RPC plus an extension-UI request/response subprotocol                                                      | Open source and substantial, but its RPC is Prime-specific rather than ACP |
| Cordis           | General plugin meta-framework used to compose services, events, and reversible effects | Typed context services, event waterfalls, plugin lifecycle, and configuration patches                            | Explicitly unstable; APIs may change without notice                        |
| DeepSeek Harness | Full agent application built on Cordis                                                 | Cordis plugins, profiles and bundles, session events, model adapters, tools, commands, and Web Client Chat nodes | Developer preview with announced compatibility-breaking changes            |

Cordis is not itself a UI platform. DeepSeek Harness supplies the Web UI, agent loop, persistence, model adapters, tools, and policy as replaceable Cordis plugins. Its `web` profile layers the browser application over `dsh-base`; its `headless` profile composes a different product from the same plugin tree.

## Prime Agent

Prime Agent is built on Pi and adds a daemon-backed runtime, persistent IPython control environment, recursive subagents, long-running goals and schedules, and a continual harness that can refine supplemental prompts, memories, skills, and subagent definitions.

Its headless RPC mode is a strict JSONL command/event protocol over standard input and output. It exposes session state, messages, model selection, abort, fork and clone operations, daemon messaging, schedules, heartbeats, and observation of other active sessions.

Extensions can ask an RPC client to render `select`, `confirm`, `input`, and multiline `editor` dialogs, and can publish notifications, status, widgets, titles, and editor text. This is useful prior art for a normalized human-interaction channel. It is not full UI portability: custom components, headers, footers, editor components, theme control, and several direct-TUI methods are unsupported or reduced to no-ops in RPC mode.

Prime Agent therefore offers strong runtime and protocol ideas, but it is not a neutral UI shell for foreign harness sessions. Using its TUI above TeleClaude adapters would require either extending Prime's proprietary RPC/runtime or translating foreign sessions into Prime's own session semantics.

## Cordis and DeepSeek Harness

DeepSeek Harness confirms that Cordis is its underlying framework. Every major product part is a plugin, including model adapters, tool registration, session logging, the agent interface, and the default agent loop. Profiles compose ordered bundles, user patches can replace configuration rows, and plugin registrations unwind when their owner unloads.

The most relevant DeepSeek Harness seams are:

- `ctx.llm` for model adapters;
- `ctx.agents` and `agent/*` events for live execution;
- the append-only `SessionEvent` log and `session/event` stream for replay and UI fidelity;
- `ConversationNodeDefinition` plus keyed renderers for custom Web Client Chat nodes;
- commands that execute without a model turn;
- injectable context, jobs, tools, terminals, sandbox, filesystem, and subprocess providers;
- separate `web` and `headless` profile compositions.

The session log is not merely presentation data: DeepSeek Harness derives model-visible history from it and requires model-visible input to be reconstructable from durable session events. That is elegant for a native DeepSeek Harness agent, but creates an authority collision when a foreign CLI owns its own transcript and continuation semantics.

No inspected official DeepSeek Harness source documents it as an ACP client or ACP host. Its architecture makes an ACP bridge plausible as a plugin, but that bridge would still have to translate ACP session updates, permissions, plans, tool activity, cancellation, and continuation into DeepSeek Harness commands and session events. ACP support must not be assumed from the plugin architecture alone.

## Implications for TeleClaude

DeepSeek Harness is the strongest candidate of these three for an experience-layer experiment, not for the adapter contract itself. A bounded spike could create a TeleClaude-owned Cordis profile in which:

- TeleClaude remains the authority for workflow state, deterministic routing, identity, availability, and logical session ownership;
- a bridge plugin consumes TeleClaude's normalized session/event stream;
- the DeepSeek Web UI renders mirrored conversation and control-plane events;
- commands call back into TeleClaude rather than selecting providers or models locally;
- the native DeepSeek model adapter and agent loop are absent for externally owned sessions.

This works only if DeepSeek Harness permits the Web UI and session renderer to operate without making its own session log the execution authority. If that cannot be achieved cleanly through public plugins and profile composition, adopting or forking the UI would import the same coupled monolith TeleClaude is trying to retire.

Prime Agent contributes different lessons: keep presentation separate from execution, make session observation and reconnection explicit, and define a small typed interaction protocol for dialogs and status. Its RPC limitations also show why a UI protocol must expose extension rendering deliberately rather than assume a harness TUI can be remotely reused.

ACP remains a plausible transport from a TeleClaude adapter or Cordis bridge to compatible native agent CLIs. It does not make either Prime Agent or DeepSeek Harness a universal frontend automatically, and it does not solve canonical history or cross-harness continuation by itself.

## Recommended investigation

1. Validate whether a minimal DeepSeek Harness profile can boot the Web UI with the native model adapter and agent loop removed.
2. Implement one read-only synthetic session plugin that renders normalized text, tool activity, approval, status, and a custom chat node from an external event source.
3. Determine whether session replay can remain presentation-only without duplicating or taking ownership of the foreign harness transcript.
4. Prototype one ACP-backed foreign session only after the read-only rendering boundary is proven.
5. Compare the result with building the same projection through AG-UI plus assistant-ui; reject Cordis if the bridge requires patching privileged product internals.

## Gaps and unknowns

- The claimed DeepSeek Harness editor mode that creates user-driven extensions on the fly has not yet been traced to an official document or source location. It should remain a research lead until the video or implementation is identified.
- Official DeepSeek Harness ACP support was not found in the inspected README and architecture documentation.
- Cordis and DeepSeek Harness both warn that their APIs are unstable, so any experiment needs a narrow replaceable boundary.
- Subscription-backed authentication behavior across Prime Agent providers was not evaluated here.

## Sources

- https://github.com/PrimeIntellect-ai/prime-agent
- https://github.com/PrimeIntellect-ai/prime-agent/blob/main/packages/coding-agent/docs/rpc.md
- https://github.com/PrimeIntellect-ai/prime-agent/blob/main/packages/coding-agent/docs/architecture.md
- https://github.com/cordiverse/cordis
- https://github.com/deepseek-ai/deepseek-harness
- https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/architecture.md
- https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/user/guide/index.md
