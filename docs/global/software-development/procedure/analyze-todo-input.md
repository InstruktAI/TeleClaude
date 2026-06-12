---
activation_trigger: 'Use when a kind-less todo needs its raw human intent interpreted and classified into a kind'
description: "Interpret a kind-less todo's raw input, assign it a kind, and route it to that kind's lifecycle entry phase through a single autonomous stamp."
visibility: 'public'
---

# Analyze Todo Input — Procedure

## Goal

Turn a kind-less brain dump into a classified, routed todo. The human offloaded
raw intent without framing it; this step frames it and hands it to the right
lane. It is an **autonomous router**: it reads the `input`, decides the kind,
and assigns it in one stamp — no proposal, no human approval gate, no idle. It
never executes the work itself and never mutates the `input`.

## Preconditions

- The todo was created without `--kind`. Its `input` artifact holds the raw dump
  and is immutable.
- `kind` is unset (`None`) and the todo carries no `lifecycle_phase` — the
  lifecycle router dispatched this step because the `workflow.todo.created` event
  carried no kind.
- The todo is not delivered or removed.

## Steps

1. **Read the `input`.** `telec todo artifacts read {slug} input`. This is the raw
   human dump — possibly fuzzy, multi-step, or a transcript of a conversation.
   Read it as intent to be interpreted, not as a spec to be obeyed literally.

2. **Classify.** Decide which kind the dump is, by what the work actually is:
   - any change to the codebase that is not a new capability or a defect → `change`;
     no pre-existing plan is required — the plan lane drafts one;
   - a new product capability that needs a PRD → `feature`;
   - a defect to fix → `bug`;
   - an operation whose work is side-effects only and never touches the codebase
     (notify someone, hit an API, run an operation, do research) → `task`.
     Anything that touches the codebase is `change` (or `feature`/`bug`), never
     `task`: a `task` is the side-effect kind and does not absorb code work.

3. **Assign the kind through the stamp boundary.**
   - For a **`task`**: draft the **`task-plan`** content from the blueprint below,
     then run `telec todo stamp {slug} --kind-assign task "<task-plan content>"`.
     The stamp fixes `kind = task`, writes the `task-plan` artifact from the
     supplied content, and sets `lifecycle_phase = KIND_ENTRY_PHASE[task]`
     (`prepared`, silent until a trigger starts it).
   - For an **SDLC kind** (`change`/`feature`/`bug`): run
     `telec todo stamp {slug} --kind-assign <kind>`. The stamp fixes `kind`,
     writes no `task-plan`, and sets `lifecycle_phase = KIND_ENTRY_PHASE[kind]`
     (`plan_drafting` for change, `prd_drafting` for feature, `diagnose` for bug).
   - Do not edit todo state directly. The stamp command is the validated
     state-write boundary and the only place kind is assigned.

4. **Done.** The assignment routes the todo into its kind's lane on the next
   dispatch; the normal orchestrator picks it up. There is nothing to wait for —
   classification is a route decision, not a request for approval.

### The `task-plan` blueprint

The task-plan is a **living document** — the durable working memory of the task.
Whoever works the task grooms it in place: ticks off steps, appends results,
re-plans the rest. It is to a task what commits are to a change. Keep it light;
more structure than this is ceremony.

- **Intent** — one line: "I read your dump as …".
- **Steps** — an ordered, checkable list. Each step is one of:
  - _do X_ — a direct action an agent performs;
  - _spawn a follow-on `task`_ — defer a later side-effect operation as another
    `task` (never code work, which is always a separate `change`/`feature`/`bug`);
  - _wait on `dep` / `time`_ — a gate before the next step.
- **Status** — per step: `todo` / `done` / `blocked`.
- **Log** — a short running record of what happened as steps complete.

Authoring discipline mirrors how you already plan your own work: externalize the
plan you would otherwise hold in session into this artifact, and keep it current.
The session is the hands; the task-plan is the memory.

## Outputs

- A todo with `kind` fixed and `lifecycle_phase = KIND_ENTRY_PHASE[kind]`.
- For a `task`: a `task-plan` artifact (intent + steps + status + log).
- The `input` artifact unchanged.

## Recovery

- If the `input` is empty or unreadable, do not guess a kind — report the blocker
  and leave the todo kind-less for the human.
- If classification is genuinely undecidable between an operation and code work,
  the discriminator is whether it touches the codebase: code work is `change`
  (or `feature`/`bug`), and only pure side-effect work is a `task`. Decide on that
  axis rather than defaulting to `task`.
- If you catch yourself executing a step rather than classifying it, stop: this
  procedure assigns a kind and (for a task) drafts the task-plan only. The work
  itself runs later, in the kind's lane.

## Discipline

You classify and route; you never act on the dump. The single failure mode here
is sliding from "classify this dump" into "do this dump" — running a step,
dispatching downstream work by hand, or editing the `input`. Read the `input`,
decide the kind, and assign it through `telec todo stamp --kind-assign` (drafting
the `task-plan` first for a task). The kind assignment is autonomous — no human
approval stands between classification and the lane — so the discipline is the
restraint to route the work, not perform it. Anything that touches the codebase is
`change` (or `feature`/`bug`), never `task`; a `task` is pure side-effect work.
