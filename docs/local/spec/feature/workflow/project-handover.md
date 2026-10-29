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
- **The giving computer winds down without waiting for running steps.** It
  starts no new orchestrator for the project. Each of its orchestrators for the
  project starts no new step, stops the step it is in at the first point where
  that step's progress is saved on the project's shared record, ends together
  with the sessions it started, and releases its claim. The receiving computer
  redoes only what was in flight and not yet saved.
- **The shared record carries the work.** What an orchestrator leaves behind
  reaches the receiving computer through the record every computer reads: the
  todo's state and artifacts in the project's workflow store, and its commits
  on the project's remote. A handover moves nothing else.
- **The receiving computer continues each released todo** in the phase it
  stood in, once its claim is released, without a person starting it. This
  holds whatever the automatic-start setting is for new work of the todo's
  kind.
- **Sessions that drive no todo stay where they are.** A person's own
  conversations, and any session that is not a todo's lifecycle orchestrator or
  one of its workers, are not ended or moved.

### What the person sees

- **One report per handover,** readable from either computer until the
  handover is complete. It names each todo that was being driven and whether it
  has moved to the receiving computer, is still winding down on the giving
  computer, or was taken over from a giving computer that did not answer.
- **When the giving computer can be closed.** The report says whether the
  giving computer still runs anything for the project. Once it runs nothing,
  the giving computer can be closed without holding up any todo.

### When a computer does not answer

- **A giving computer that does not answer** does not hold its todos back. The
  receiving computer takes each of them over at once, from its last saved
  state. Once a todo has moved, the giving computer can no longer change its
  state, its artifacts or its work. When it is back, it ends its orchestrators
  for the project.
- **A receiving computer that does not answer, or holds no checkout of the
  project,** is refused before anything changes, naming why. The active
  computer and every orchestrator stay as they were.
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

#### UC-PH4: Hand a project over while the laptop is asleep

```gherkin
Given a person whose project's active computer is their laptop, which is asleep
And orchestrators on the laptop were driving some of the project's todos
When the person hands the project over to their always-on computer from elsewhere
Then the always-on computer drives each of those todos at once, from its last saved state
And once the laptop wakes, it changes none of those todos
```

#### UC-PH5: A computer that cannot take the project is refused

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
