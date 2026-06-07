---
id: 'software-development/procedure/analyze-todo-input'
type: 'procedure'
domain: 'software-development'
scope: 'domain'
visibility: 'public'
activation_trigger: 'Use when a kind-less todo needs its raw human intent interpreted and classified into a kind'
description: 'Interpret a kind-less todo''s raw input, classify it into a kind, and propose it for human approval — writing a task-plan when the dump is a task, or setting an SDLC kind so the normal lane takes over.'
---
# Analyze Todo Input — Procedure

## Goal

Turn a kind-less brain dump into a classified, approvable todo. The human offloaded
raw intent without framing it; this step frames it for them. It **proposes** — it
never executes the work, and it never mutates the `input`.

## Preconditions

- The todo was created without `--kind`. Its `input` artifact holds the raw dump
  and is immutable.
- `lifecycle_phase` is `unkinded` — the lifecycle router dispatched this step
  because the `workflow.todo.created` event carried no kind.
- The todo is not delivered or removed.

## Steps

1. **Read the `input`.** `telec todo artifacts read {slug} input`. This is the raw
   human dump — possibly fuzzy, multi-step, or a transcript of a conversation.
   Read it as intent to be interpreted, not as a spec to be obeyed literally.

2. **Classify.** Decide which kind the dump is, by what the work actually is:
   - clean code work with a knowable plan → `change`;
   - new capability that needs a PRD → `feature`;
   - a defect to fix → `bug`;
   - fuzzy / multi-step / an action whose work need not touch the codebase
     (notify someone, hit an API on a schedule, run an operation, or fan out into
     several of the above) → `task`.
   When the dump is genuinely ambiguous between an action and code work, prefer
   `task`: a task can itself spawn `change`/`bug` todos, so it is the safe
   container for "do some of this now, defer the code work."

3. **Write the proposal and set the proposed kind.**
   - For a **`task`**: write the **`task-plan`** artifact (see the blueprint below)
     and set kind = `task`. The task-plan opens with your one-line read of the
     intent, then the steps. This single artifact is both the classification you
     are proposing and the actionable bookkeeping.
   - For an **SDLC kind** (`change`/`feature`/`bug`): set the kind with a one-line
     rationale; the kind's normal lane produces its own artifacts (PRD,
     `implementation-plan`). Do not write a `task-plan`.
   The todo lands at `lifecycle_phase = kind_proposed`. **Stop here** — do not
   execute steps, do not dispatch downstream work.

4. **Go idle.** The human reviews the proposal (`telec todo show {slug}` /
   `artifacts read {slug} task-plan`) and approves or corrects the kind. On
   approval the todo enters the assigned kind's normal entry; for a `task` it sits
   silent until the human or a dependency/time trigger starts it.

### The `task-plan` blueprint

The task-plan is a **living document** — the durable working memory of the task.
Whoever works the task grooms it in place: ticks off steps, appends results,
re-plans the rest. It is to a task what commits are to a change. Keep it light;
more structure than this is ceremony.

- **Intent** — one line: "I read your dump as …".
- **Steps** — an ordered, checkable list. Each step is one of:
  - *do X* — a direct action an agent performs;
  - *spawn `todo(kind=…)`* — create/defer a child todo (e.g. the code work as a
    `change`, a later action as another `task`);
  - *wait on `dep` / `time`* — a gate before the next step.
- **Status** — per step: `todo` / `done` / `blocked`.
- **Log** — a short running record of what happened as steps complete.

Authoring discipline mirrors how you already plan your own work: externalize the
plan you would otherwise hold in session into this artifact, and keep it current.
The session is the hands; the task-plan is the memory.

## Outputs

- A todo at `lifecycle_phase = kind_proposed` with a proposed kind set.
- For a `task`: a `task-plan` artifact (intent + steps + status + log).
- For an SDLC kind: the kind set with a one-line rationale; no `task-plan`.
- The `input` artifact unchanged.

## Recovery

- If the `input` is empty or unreadable, do not guess a kind — report the blocker
  and leave the todo `unkinded` for the human.
- If classification is genuinely undecidable, propose `task` (the safe container)
  and say so in the task-plan's intent line; the human can redirect on approval.
- If you catch yourself executing a step rather than proposing it, stop: this
  procedure classifies and plans only. Execution happens after human approval, in
  the kind's lane.

## Discipline

You propose; you never act. The single failure mode here is sliding from "classify
this dump" into "do this dump" — running a step, dispatching downstream work, or
editing the `input`. Read the `input`, classify, write the proposal (a `task-plan`
for a task, a kind + rationale otherwise), and go idle. The human's approval is the
gate between your proposal and any work. When unsure between an action and code
work, `task` is the safe container — it can always spawn the code work later.
