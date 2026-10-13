---
description: Command-and-argument input on the TUI new-session modal and Discord conversation
  surfaces, with uniform command loading and preserved session authority.
---

# Interactive Command Input — Spec

## What it is

A human operator invokes an installed TeleClaude command by entering its name
and arguments in the TUI New Session modal or by sending that text through the
Discord adapter. A leading slash is optional on these surfaces. Each supported
agent receives the same explicit command-document loader.

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

<!-- planned-change:procedure-role-capability-composition -->

- The leading token is resolved exactly against the installed command corpus;
  the remaining text supplies the command's arguments. No natural-language
  intent classification, fuzzy matching, or command allowlist copied from the
  lifecycle role map participates in recognition.

<!-- change:procedure-role-capability-composition -->

- The leading token is resolved exactly against the published entry
  procedures by snippet ID; the remaining text supplies the procedure's
  arguments. No natural-language intent classification, fuzzy matching, or
  allowlist copied from any role table participates in recognition.

<!-- /planned-change:procedure-role-capability-composition -->
<!-- planned-change:procedure-role-capability-composition -->

- The command-input owner reuses the canonical document resolver and loader.
  Transport edges declare input intent and carry caller evidence; they do not
  author a parallel loader or decide role permissions.

<!-- change:procedure-role-capability-composition -->

- The command-input owner reuses the procedure-entry resolution and loader.
  Transport edges declare input intent and carry caller evidence; they do not
  author a parallel loader or decide role permissions.

<!-- /planned-change:procedure-role-capability-composition -->

- Human input that does not resolve to an installed command remains ordinary
  conversation. Quoted examples and fenced code do not become commands merely
  because they contain a command name. A recognized invocation that violates
  an existing argument or authorization rule is refused visibly.

<!-- planned-change:procedure-role-capability-composition -->

- For a newly created command session, command identity and applicable role,
  job, working-slug metadata, and required execution context are established
  through canonical command creation. Worktree-bound commands derive their
  execution context from the command and work item without extra modal input.
  Existing-session normalization preserves that session's authority; an
  invoked operation retains its own claim/adoption contract.

<!-- change:procedure-role-capability-composition -->

- For a newly created session, the procedure, its declared role, working-slug
  metadata, and required execution context are established through the
  procedure-entry contract. Worktree-bound procedures derive their execution
  context from the procedure and work item without extra modal input.
  Existing-session normalization preserves that session's authority and role;
  an invoked operation retains its own claim/adoption contract.

<!-- /planned-change:procedure-role-capability-composition -->

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

#### UC-ICI1: Command startup from the TUI

```gherkin
Scenario Outline: An operator starts a command from the new-session modal
  Given a human operator has selected a project and an available agent in the TUI New Session modal
  And the requested TeleClaude command is installed and its arguments are valid
  When the operator submits "<input>" as the initial message
  Then the new agent session receives the explicit command-loading instruction with the supplied arguments
  And the session is identified by the requested command and its applicable role and work item
  And the command-loading behavior is the same for every supported agent

  Examples:
    | input                    |
    | integrate           |
    | /integrate          |
    | prepare example-item |
    | /prepare example-item |
```

#### UC-ICI2: Command input through Discord

```gherkin
Scenario Outline: A human invokes a command in the Discord conversation
  Given a human operator is authorized to invoke the installed command in the Discord conversation
  And the conversation is a "<surface>" with a "<binding>"
  When the operator sends the command name with its arguments, with or without a leading slash
  Then the agent receives the explicit command-loading instruction and the supplied arguments once
  And the command runs in the session selected by that conversation's existing routing contract

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
When their text does not begin with an installed command invocation
Then the text follows ordinary conversation delivery without a command loader
And mentioning a command in prose or quoting a command example does not activate it
```

#### UC-ICI4: Surface confinement

```gherkin
Given a human or agent sends a bare command name as ordinary text outside the TUI New Session modal and Discord human-to-agent text input
When the platform processes that text
Then this shorthand capability does not reinterpret it as a command
And explicit command-dispatch requests retain their existing loading behavior
```

#### UC-ICI5: Existing authority remains binding

```gherkin
Given a human sends command input through Discord
When session creation or an operation performed by the command requires authority the caller does not hold
Then that operation is refused visibly by its existing authority gate
And interpreting the text does not grant privileges or bypass workflow ownership
```

#### UC-ICI6: Invalid arguments are visible

```gherkin
Given a human enters an installed command on an enabled shorthand surface
When the supplied arguments violate that command's existing admission rules
Then the human receives the corresponding refusal
And the command is not silently delivered as ordinary text
```

#### UC-ICI7: Owning-computer command resolution

### Cross-context references

- **agent_runtime** owns command interpretation, session acceptance, and command
  execution through its published input and session-creation contracts.
- **integration** owns Discord ingress and conversation binding, including the
  distinction between newly created and existing sessions.
- **identity** owns caller evidence and clearance; this capability consumes its
  current decisions without adding or widening permissions.
- **context** owns the installed command corpus.

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
