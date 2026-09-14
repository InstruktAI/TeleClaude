---
number: 88
date: 2026-09-14
description: Documentation and agent-artifact deployment runs at the commit boundary; the filesystem watcher is retired and the deploy command keeps only explicit callers.
---

# Deployment Happens At The Commit Boundary — ADR

## Context

Documentation and agent-artifact deployment was driven by a long-lived filesystem watcher. It observed every registered project root and invoked a deploying synchronization whenever a file under the documentation or agent-artifact trees was saved.

Deploying on save means deploying uncommitted, mid-edit state. That forced a validation bypass into the deploy command, because live reload must never block on a file caught halfway through an edit, and the bypass in turn needed an environment gate to keep every other caller — agents especially — from reaching it. It also established an ambient writer: a background process mutating machine-wide runtime state, and repository state, between commits, with no committed source to attribute the result to. Responsibilities accreted into the deploy command precisely because that command already ran on every save, which made each addition ambient by inheritance.

Two conditions removed the reason for that arrangement. Source validation moved to the commit gate, so committed state is validated state. Deterministic post-commit maintenance moved into a git hook (ADR-0087), establishing the commit boundary as a point at which work runs automatically for every committer.

The fork was whether to keep the watcher for low-latency reload, or to deploy at the commit boundary and retire it.

## Decision

Deployment runs at the commit boundary. The filesystem watcher is retired.

The deploy command remains directly invocable; it loses its ambient caller, not its existence. Its callers become the post-commit hook and project bootstrap, plus a person or agent invoking it deliberately. Its validate-only and validation-bypass modes are retired with the watcher: the commit gate validates, so there is nothing for a deploy-time bypass to skip and nothing for a validate-only mode to perform.

## Consequences

- Deployed artifacts reflect committed state. Between a save and its commit, the deployed tree is the previous commit's.
- No process mutates machine-wide or repository state between commits.
- The validation bypass and its environment gate disappear, along with the class of caller that needed to deploy unvalidated state.
- Deployment composes machine-global state across every registered publisher root, so it stays directly invocable: a fresh clone, a newly registered project, or a recovery after a failed run each need a deployment with no commit to trigger it.
- Serialization and atomic snapshot publication are retained. Commit pacing removes the save-storm case but not concurrency: separate checkouts on one machine can still deploy at once, and a reader must still observe a complete snapshot.
- Reading through the documentation retrieval surface resolves from source and is unaffected by deployment timing. The deployed domain bundle that agent baselines point at is the one surface where the gap between a save and its commit is observable.

## Alternatives Considered

- Retain the watcher for live reload alongside commit-boundary deployment. Rejected: two deployment paths keep the ambient writer and require retaining the validation bypass to serve it, preserving the whole class of problem in exchange for a latency window the author closes with their own commit.
- Deploy from the pre-commit gate instead. Rejected: it would deploy state that may fail validation or may never be committed, so the deployed tree could describe a commit that does not exist.
- Trigger deployment from a daemon poll over the registered roots. Rejected: the same ambient class as the watcher with a coarser trigger, and it reintroduces mutation with no committed source to attribute it to.
