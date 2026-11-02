---
description: 'Canonical definition of the `spike` todo kind — a pre-authorized task that verifies third-party behavior and records it in third-party documentation, the only repository change it makes.'
delivered_by: [spike-todo-kind]
---

# Todo Kind: Spike — Spec

## What it is

`spike` is one of the five canonical todo kinds. A spike answers a question
about third-party behavior that a waiting decision rests on, and records the
verified answer where every later agent reads it. It runs as a task
(`sdlc/spec/todo-kind-task`): it is drafted into a `task-plan` by
`sdlc/procedure/lifecycle/task/prepare-task` and executed by
`sdlc/procedure/lifecycle/task/run-spike`, outside the SDLC prepare and work
machines. When to file one is `sdlc/policy/research-spikes`.

## Canonical fields

- **Differences from a task.** A spike shares the task lane with three
  differences:
  - **Pre-authorized as a class.** No human authorizes a spike. Its
    `task-plan` confines the run to research and to live tests on throwaway
    resources the run creates and removes itself; it never touches live data
    or a resource it did not create.
  - **It commits documentation, and nothing else.** A spike commits only to
    its project's third-party documentation (`general/spec/third-party-docs`)
    and its project's exploration home (`general/spec/exploration-home`).
    Every other repository change stays outside it, as it does for a task.
  - **Its plan names the research procedure.** Every spike `task-plan` names
    `sdlc/procedure/research/third-party-research` as the procedure the run
    follows.
- **Result destinations.** A spike produces no artifact of its own kind:
  - verified facts about one upstream party go into that party's third-party
    documentation, project or global by the placement rule of
    `general/spec/third-party-docs`. A global finding authored outside the
    project that owns the global documentation travels by the cross-project
    documentation route (`general/policy/documentation-discipline`);
  - the exploration trail — hypotheses, evidence, what was tried — goes into
    the exploration home;
  - the run record — what was tested, the evidence, the resources created and
    their removal — goes into the spike's `log`, which ends with the answer
    to the question the spike was filed for;
  - the conclusion for the waiting decision is written by the waiting job into
    its own artifact when it resumes (`sdlc/policy/research-spikes`).
- **One firing.** A spike runs once. It carries no `schedule`, and a
  successful run delivers it.
- **Discriminator.** Does the work exist to verify third-party behavior a
  decision rests on, and is documentation its only lasting effect? Yes →
  `spike`. Side effects only → `task`. Any other repository change →
  `change`, `feature` or `bug`.

## Known caveats

- A spike is never repository work on the GitHub workflow store, as a task is
  not; a job that waits on a spike shows a dependency the board does not list.
- A spike that cannot verify a behavior with throwaway resources records what
  remains unverified and still completes; its dependent decides with that gap
  visible.
