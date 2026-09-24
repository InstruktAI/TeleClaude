---
description: 'Automation that rebuilds and deploys agent artifacts when sources change.'
visibility: 'public'
---

# Agent Artifact Automation — Spec

## What it is


Commit-boundary automation that rebuilds and deploys agent artifacts when a
commit changes agent sources or documentation in this repo. Nothing deploys
between a save and its commit.


## Canonical fields


- **Trigger**: a validated canonical commit or merge whose changed paths bind the publication action.
- **Command**: commit or merge maintenance invokes the internal publication action for its recorded range after the commit gate has validated it.


## Allowed values

- None.

## Known caveats


- A commit made on a host where the hook is not installed distributes nothing
  and surfaces no obligation. Recovery replays the recorded maintenance action;
  it never publishes the current working tree.
- Generated artifacts are overwritten on the next automated run.
