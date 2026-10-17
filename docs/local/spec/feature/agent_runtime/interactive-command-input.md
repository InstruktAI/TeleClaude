---
description: Command-and-argument input on the TUI new-session modal and Discord conversation
  surfaces, with uniform command loading and preserved session authority.
---

# Interactive Command Input — Spec

## What it is

A human operator invokes a published entry procedure by entering its snippet ID
and arguments in the TUI New Session modal or by sending that text through the
Discord adapter. A leading slash is optional on these surfaces. Each supported
agent receives the same loader, which directs it to retrieve the procedure's
instructions.

The TUI operation creates the requested session. Discord retains its existing
conversation binding: a message that creates a session is its first input, and
a message for an existing session runs there. A launcher-created empty session
is an existing session for this purpose. Command input does not itself replace
the session, switch its agent, grant privileges, or change an existing session's
role or workflow ownership. An invoked workflow retains its existing authority
to claim work and adopt the corresponding role through its own operations.

## Canonical fields

### Recognition and ownership

- Shorthand recognition is enabled by the TUI New Session submission and by
  Discord's human-to-agent text ingress. It is not inferred from terminal
  identity, a session's historical origin, or message text claiming an origin.

- The leading token is resolved exactly against the published entry
  procedures by snippet ID; the remaining text supplies the procedure's
  arguments. No natural-language intent classification, fuzzy matching, or
  allowlist copied from any role table participates in recognition.

- The command-input owner reuses the procedure-entry resolution and loader.
  Transport edges declare input intent and carry caller evidence; they do not
  author a parallel loader or decide role permissions.

- Human input that does not resolve to a published entry procedure remains
  ordinary conversation. Quoted examples and fenced code do not become
  invocations merely because they contain a procedure ID. A recognized
  invocation that violates an existing argument or authorization rule is
  refused visibly.

- For a newly created session, the procedure, its declared role, working-slug
  metadata, and required execution context are established through the
  procedure-entry contract. Worktree-bound procedures derive their execution
  context from the procedure and work item without extra modal input.
  Existing-session normalization preserves that session's authority and role;
  an invoked operation retains its own claim/adoption contract.

- Discord sender identity is evaluated for the current message. Permission to
  converse in a channel does not confer permission to create a privileged role.
- Discord invitation, bot filtering, channel ownership, customer/help-desk,
  relay, attachment, and native interaction handling retain their contracts.
  Only text routed to an agent enters shorthand recognition.
- Accepted command input follows ordinary durable input acceptance and
  occupancy-aware delivery, retaining the human actor, original command text,
  and source occurrence separately from generated loader content. Command
  expansion is performed once, and retries do not wrap a loader again.
- Non-Discord adapters, ordinary CLI/API messages, peer messages, and text typed
  directly into an agent's native composer acquire no shorthand interpretation
  from this capability. Explicit command dispatch retains its current contract.

### Use cases

#### UC-ICI1: An operator starts a procedure from the TUI with its arguments

```gherkin
Scenario Outline: Start a new session from a published procedure
  Given an operator has selected a project and an available agent in the TUI New Session modal
  And the operator wants to run a published entry procedure with valid arguments
  When they submit "<input>"
  Then the new session carries the procedure, its declared role, and work item
  And the agent's first instruction directs it to retrieve and follow that procedure
  And the same procedure and arguments work with every supported agent

  Examples:
    | input                                                   |
    | sdlc/procedure/lifecycle/integrate                      |
    | /sdlc/procedure/lifecycle/integrate                     |
    | sdlc/procedure/lifecycle/prepare/overview example-item  |
    | /sdlc/procedure/lifecycle/prepare/overview example-item |
```

#### UC-ICI2: An operator invokes a procedure in a Discord conversation

```gherkin
Scenario Outline: A human invokes a procedure in the Discord conversation
  Given an operator wants to run a published entry procedure in a Discord conversation
  And the conversation is a "<surface>" with a "<binding>"
  When the operator sends the procedure ID with its arguments, with or without a leading slash
  Then the session selected by the conversation receives the procedure's loader once
  And the loader carries the arguments and directs the agent to retrieve and follow the procedure
  And a session created by the message receives it as initial input

  Examples:
    | surface       | binding                      |
    | project thread | session created by this input |
    | project thread | launcher-created empty session |
    | project thread | existing conversation session |
    | team channel  | existing conversation session |
    | direct message | session created by this input |
    | direct message | existing personal session    |
```

#### UC-ICI3: Non-command text remains conversation

```gherkin
Given a human uses the TUI New Session modal or Discord text input
When their text does not begin with a published entry procedure invocation
Then the text follows ordinary conversation delivery without a command loader
And mentioning a command in prose or quoting a command example does not activate it
```

#### UC-ICI4: A person can use ordinary text outside the shorthand surfaces

```gherkin
Given a person sends text to an agent through terminal, CLI/API, or a non-Discord adapter
When the input reaches the agent session
Then this shorthand capability does not reinterpret it as a procedure invocation
And explicit command-dispatch requests retain their existing behavior
```

#### UC-ICI5: Existing authority remains binding

#### UC-ICI6: An operator receives a visible refusal for an invalid invocation

#### UC-ICI7: Owning-computer command resolution

### Cross-context references

- **agent_runtime** owns command interpretation, session acceptance, and command
  execution through its published input and session-creation contracts.
- **integration** owns Discord ingress and conversation binding, including the
  distinction between newly created and existing sessions.
- **identity** owns caller evidence and clearance; this capability consumes its
  current decisions without adding or widening permissions.

- **context** owns the published procedures and their entry declarations.

## Known caveats

Shorthand normalization in an existing session does not perform a role
conversion. Operations inside the command remain subject to existing clearance
and workflow ownership rules, including authorized claim/adoption transitions.

Discord slash-prefixed input here is ordinary message content delivered to the
adapter. Native Discord application-command interactions have their separate
contract; this capability registers no application commands.

## See Also

- docs/local/spec/feature/agent_runtime/run-session-with-command.md
- docs/local/spec/feature/agent_runtime/session-input-delivery.md
- docs/local/spec/feature/integration/discord-dm-personal-assistant-routing.md
- docs/local/spec/feature/integration/conversation-only-adapters.md
- docs/local/spec/feature/identity/command-clearance.md
- docs/local/design/architecture/layer-ownership.md
- ~/.teleclaude/docs/sdlc/policy/domain-ownership.md
- ~/.teleclaude/docs/general/policy/human-contract.md
