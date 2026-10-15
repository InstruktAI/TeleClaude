---
description: GitHub-hosted macOS runner lifecycle, the arm64 nested-virtualization limit, and how a job identifies a hosted runner.
---

# Hosted macOS runners

Each GitHub-hosted runner is a new virtual machine that GitHub provisions for
one job and decommissions when the job finishes. The `macos-latest` label
selects an arm64 (Apple silicon) macOS image. Arm64 macOS runners do not
support nested virtualization, a limitation of the Apple Virtualization
Framework that GitHub's hypervisor uses, so a job cannot start its own macOS
or Linux virtual machine on them.

Every job receives the default variable `RUNNER_ENVIRONMENT`, set to
`github-hosted` on GitHub-hosted runners and `self-hosted` on self-hosted
runners, alongside `GITHUB_ACTIONS=true`. Default `GITHUB_*` and `RUNNER_*`
variables cannot be overwritten by the workflow.

Runner images ship preinstalled developer tooling; the macOS image inventory
lists it per image version.

## Sources

- https://docs.github.com/en/actions/reference/runners/github-hosted-runners — per-job VM lifecycle, runner labels, and the arm64 macOS nested-virtualization limitation.
- https://docs.github.com/en/actions/how-tos/manage-runners/github-hosted-runners/use-github-hosted-runners — provisioning and decommissioning per job.
- https://docs.github.com/en/actions/reference/workflows-and-actions/variables — `RUNNER_ENVIRONMENT` and `GITHUB_ACTIONS` default variables.
- https://github.com/actions/runner-images — macOS image software inventories.
