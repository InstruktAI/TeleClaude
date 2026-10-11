---
description: GitHub-hosted Ubuntu VM isolation and privileges used for real daemon and CLI acceptance.
---

# Hosted runtime validation

Standard GitHub-hosted Ubuntu jobs run in fresh virtual machines. The Linux
runner has passwordless sudo, allowing ordinary service installation inside the
job VM. The Ubuntu runner image inventory includes systemd. The lightweight ubuntu-slim label uses an unprivileged container on a shared VM.
It lacks the administrative capabilities of standard VM runners. GitHub
provisions the container for the job and decommissions it when the job finishes.

## Sources

- https://docs.github.com/en/actions/reference/runners/github-hosted-runners — standard VM lifecycle, runner labels and administrative privileges.
- https://github.com/actions/runner-images/blob/main/images/ubuntu/Ubuntu2404-Readme.md — current Ubuntu image software inventory.
