---
description: GitHub-hosted Ubuntu VM isolation and privileges used for real daemon and CLI acceptance.
---

# Hosted runtime validation

Standard GitHub-hosted Ubuntu jobs run in fresh virtual machines. The Linux
runner has passwordless sudo, allowing ordinary service installation inside the
job VM. The Ubuntu runner image inventory includes systemd. A full runtime
journey can therefore use the normal OS home and service lifecycle inside that
VM; redirecting a home directory alone is not equivalent process or socket
isolation.

The lightweight ubuntu-slim label uses a container and lacks the privileges of
the standard VM. It does not supply the same service-installation environment.
A repository requiring systemd lifecycle chooses a standard Ubuntu VM label.

Job isolation does not remove cleanup obligations inside a running job. A
harness retains failure evidence and stops its own services and descendants;
GitHub's job teardown supplies the final disposable-machine boundary.

## Sources

- https://docs.github.com/en/actions/reference/runners/github-hosted-runners — standard VM lifecycle, runner labels and administrative privileges.
- https://github.com/actions/runner-images/blob/main/images/ubuntu/Ubuntu2404-Readme.md — current Ubuntu image software inventory.
