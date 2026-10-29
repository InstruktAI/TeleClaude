---
description: A person hands a GitHub-backed project's running work from its active computer to another computer with one command, in either direction; the orchestrators on the giving computer finish their current step, leave their work on the shared record and end, and the receiving computer continues each todo where it stood.
delivered_by:
  - active-computer-handover
---

# Project Handover — Spec

## What it is

The behavioral contract for handing a project on the GitHub workflow store from
its active computer to another computer that holds a checkout of it. A person,
or an agent acting for them, runs one command from any computer, naming the
project and the computer that is to take it over.

**Business value:** a person who works on one project from a laptop and an
always-on computer moves the running work to the always-on computer just before
closing the laptop, and moves it back when the laptop is open again. Work
started on either computer continues on the other without anyone restarting
it, and nothing done before the handover is lost or done twice.

Which computer may start a todo's orchestrator, and that one todo has at most
one live orchestrator across computers, is decided by driver admission
(`local/projects/teleclaude/spec/feature/workflow/driver-admission`). The
handover changes which computer is active and moves the todos already being
driven; it relies on driver admission for everything a start decides.

## Canonical fields

### Who and where

- **Reach:** whoever may set the project's active computer, and an agent
  acting for such a person, such as their personal assistant.
- **Addressing:** the command names the project, by the directory it runs in or
  by its project root, and the receiving computer. It can be run from either
  computer, or from any other.
- **Both directions:** handing the project back is the same act with the two
  computers' roles swapped.

### What a handover does

- **The receiving computer becomes active.** From then on it starts the
  project's todos that no orchestrator drives, as the active computer does.
- **The giving computer winds down.** It starts no new orchestrator for the
  project. Each of its orchestrators for the project starts no new step,
  finishes the step it is in, leaves what that step produced on the project's
  shared record, ends together with the sessions it started, and releases its
  claim. An orchestrator that is waiting, on a person, a review or anything
  else, is already between steps and ends without delay.
- **The shared record carries the work.** What an orchestrator leaves behind
  reaches the receiving computer through the record every computer reads: the
  todo's state and artifacts in the project's workflow store, and its commits
  on the project's remote. A handover moves nothing else.
- **The receiving computer continues each released todo** in the phase it
  stood in, once its claim is released, without a person starting it. This
  holds whatever the automatic-start setting is for new work of the todo's
  kind, because someone already chose to drive that todo.
- **Sessions that drive no todo stay where they are.** A person's own
  conversations, and any session that is not a todo's lifecycle orchestrator or
  one of its workers, are not ended or moved.

### What the person sees

- **One report per handover,** readable from either computer until the
  handover is complete. It names each todo that was being driven and whether it
  has moved to the receiving computer, is still finishing a step on the giving
  computer, or is waiting for a giving computer that does not answer.
- **When the giving computer can be closed.** The report says whether the
  giving computer still runs any step for the project. Once it runs none, the
  giving computer can be closed without holding up any todo.

### When a computer is not there

- **A giving computer that does not answer** cannot be told to wind down. Its
  claims stay held, as driver admission keeps a claim whose computer does not
  answer. The receiving computer meanwhile takes up the todos that no
  orchestrator drives. When the giving computer answers again, it winds down
  its orchestrators for the project in the same way, and the receiving computer
  continues their todos.
- **A receiving computer that cannot take the project** — it does not answer,
  or holds no checkout of the project — is refused before anything changes,
  naming why. The active computer and every orchestrator stay as they were.
- **Handing a project to the computer that is already active** changes nothing
  and says so.

### Use cases

#### UC-PH1: Hand a project over before closing the laptop

```gherkin
Given a person whose project's active computer is their laptop
And orchestrators on the laptop are driving some of the project's todos
When the person hands the project over to their always-on computer
Then each of those todos is continued on the always-on computer in the phase it stood in
And what the laptop's orchestrators had produced is there for the always-on computer
And the person sees when the laptop can be closed without holding up any todo
```

#### UC-PH2: Hand a project over while the giving computer is away

```gherkin
Given a person whose project's active computer is their laptop, which is asleep
And orchestrators on the laptop were driving some of the project's todos
When the person hands the project over to their always-on computer
Then the always-on computer takes up the project's todos that no orchestrator drives
And the person sees the laptop's todos as waiting on the laptop
And once the laptop is back, those todos are continued on the always-on computer
```

#### UC-PH3: A computer that cannot take the project is refused

```gherkin
Given a person whose project's active computer is their laptop
When the person hands the project over to a computer that does not answer or has no checkout of it
Then the handover is refused, naming why
And the laptop stays the project's active computer, with its orchestrators running as before
```

## Known caveats

- Only projects on the GitHub workflow store are handed over. A project on the
  local store lives on one computer; its todo state is moved with todo state
  transfer (`local/projects/teleclaude/spec/feature/workflow/todo-state-transfer`).
- A handover covers one project. Several projects are handed over one by one.
- Integrating finished work into main is not part of a handover: it is not
  tied to the project's active computer.
- A task firing in progress finishes where it runs.
