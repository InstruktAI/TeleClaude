---
description: Tart Runner Fleet Linux guest lifecycle, scale-set routing, credential boundaries and external VM inventory limits.
---

# Tart Runner Fleet Linux runners

Tart Runner Fleet supplies disposable Ubuntu ARM64 runners on Apple Silicon
through an unprivileged host controller and a released guest bootstrap helper.
The Linux base image supplies both the Actions runner and the matching helper;
Fleet does not build that image.

The scale-set name is an advertised job label. A workflow can request that name
as one string. The host controller holds GitHub App administrative credentials;
the guest receives only its runner's one-use JIT configuration over stdin.
Organization-scoped runner administration uses the App's organization
self-hosted-runner permission. Actions-read access is additionally needed when
canonical workflow-job inventory is enabled.

The controller retains lifecycle state durably and reconciles its owned guests
through cleanup after interruption or restart. Cleanup failures remain recorded.
VMs outside its inventory are not included in its shared resource budget.
Resource coexistence with external VM controllers is not established by those
upstream guarantees. Guest disposal does not prove an application's credential
refresh was settled.

## Sources

Verified source revision: `4105d3c7f0ec42aef3a55451642393e9e8587b43`.

- https://github.com/vitalyiegorov/tart-runner-fleet/blob/4105d3c7f0ec42aef3a55451642393e9e8587b43/INSTALL.md
- https://github.com/vitalyiegorov/tart-runner-fleet/blob/4105d3c7f0ec42aef3a55451642393e9e8587b43/docs/LINUX_BASE_IMAGE.md
- https://github.com/vitalyiegorov/tart-runner-fleet/blob/4105d3c7f0ec42aef3a55451642393e9e8587b43/docs/OPERATIONS.md
- https://github.com/vitalyiegorov/tart-runner-fleet/blob/4105d3c7f0ec42aef3a55451642393e9e8587b43/internal/app/inventory.go
- https://github.com/vitalyiegorov/tart-runner-fleet/blob/4105d3c7f0ec42aef3a55451642393e9e8587b43/internal/adapters/githubscaleset/provision.go
- https://github.com/vitalyiegorov/tart-runner-fleet/blob/4105d3c7f0ec42aef3a55451642393e9e8587b43/internal/lifecycle/executor.go
- https://github.com/vitalyiegorov/tart-runner-fleet/blob/4105d3c7f0ec42aef3a55451642393e9e8587b43/internal/guestbootstrap/bootstrap.go
