---
number: 87
date: 2026-09-14
description: Deterministic post-commit maintenance executes in a git post-commit hook; the checkpoint registry retains only actions whose outcome requires an agent's judgment.
---

# Mechanical Maintenance Executes In A Hook — ADR

## Context

The checkpoint engine blocks an agent's stop until it has evidence that the agent performed the maintenance its changed paths owe. Its action registry had grown to seven entries: `install`, `deps`, `restart`, `tui-reload`, `sync`, `log-check`, and `test`.

Five of those are deterministic commands — `make install`, `uv sync`, `make restart`, `telec reload`, and a validating sync. None carries a decision. They became checkpoint obligations because the checkpoint was the only mechanism that ran after a commit; no automatic post-commit execution existed, so the surface that already ran acquired the work.

Two costs followed. Compliance for a deterministic action is _inferred_ rather than established: evidence detection matches configured substrings against Bash tool-call commands in the turn timeline, and a dedicated matcher exists because naive substring matching produced false positives against mentions that were not invocations. The engine therefore runs free-text inference over a transcript to guess whether a command ran, which is the layer `general/principle/intelligence-boundaries` reserves for questions code cannot answer — and whether a command ran is not one of them. Separately, the mechanism reaches only agents: a human committing the same paths receives no obligation, because there is no agent turn to block.

The fork was whether the checkpoint should remain the execution lever for all post-commit maintenance, or whether deterministic work should execute automatically and the checkpoint retain only what requires judgment.

## Decision

Deterministic post-commit maintenance executes in a git `post-commit` hook, automatically, for every committer. Each step reports through the structured logging boundary.

The checkpoint registry retains only actions whose substance is a judgment an agent must make and act on: reading the post-commit record for anomalies, and routing post-commit review. An action is eligible for the checkpoint registry only when its outcome cannot be established by the mechanism that performs it.

## Consequences

- Deterministic maintenance no longer depends on transcript inference. It either ran or it did not, and its record is a log entry rather than a substring match against a tool call.
- Commits made by a human receive the same maintenance as commits made by an agent.
- The checkpoint becomes a short list of genuine judgment obligations. A long list of mechanical instructions trains its readers to pattern-match past it, which costs the attention the surviving obligations depend on.
- Reading the post-commit record becomes the general verification surface for this work: the hook reports what it did, and an agent judges whether it went well. Verification is retained where it needs intelligence and dropped where it does not.
- Restarting the daemon executes inside the commit rather than at the agent's stop boundary. Agent sessions are tmux-hosted and independent of daemon process lifetime, so this does not disturb the session that committed.
- A commit made where the hook is not installed performs no maintenance and surfaces no obligation for it. Hook installation becomes load-bearing in a way checkpoint delivery was not, and the absence of a hook is silent at the moment it matters.

## Alternatives Considered

- Retain all seven actions as checkpoint obligations and strengthen evidence matching. Rejected: it invests further in inferring a fact that the performing mechanism can establish directly, and each strengthening of a free-text matcher is a step further into the layer that principle excludes.
- Execute the mechanical work from a daemon or filesystem watcher on change. Rejected: ambient execution untethered from the commit boundary is what produced the accreted responsibilities this decision removes, and it mutates machine state between commits with no committed source to attribute the result to.
- Keep the daemon restart at the stop boundary and move only the remaining four. Rejected: the ordering hazard that would justify the exception does not exist, because tmux-hosted sessions survive a daemon restart, so the split would preserve a special case with no remaining reason.

## Status

Superseded in part by ADR-0100: the hook remains the automatic trigger, while maintenance execution no longer holds the Git command open.

Superseded in part by ADR-0130: commit-boundary maintenance of the platform's project no longer activates the platform; installing a release does.
