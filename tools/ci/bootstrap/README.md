# Fresh machine bootstrap harness

This harness launches a disposable macOS VM with Tart, installs the checkout
from its committed Git bundle, checks startup and documentation publication,
then reports role and identity probes. It records exact VM ownership before
creation, confirms disposal before settling that record, and leaves unfinished
ownership for the next host-admission recovery when interrupted.

The runner requires a macOS host, the Tart version checked by the command, and
the documented platform prerequisites in the base image. The release workflow
must provide an immutable `--base-image`, exact `--vm-name`, `--vm-cpu`,
`--vm-memory-mib`, and `--output-dir`. The host must have the qualified Fleet
controller and its private configuration installed; invoke the harness through
the release workflow so the host guard and workflow run identity are present.

The seed files contain only `.invalid` addresses. The owner seed is supplied
to the guest install through the install-only environment inputs. The people
seed drives the configuration and access-scope probes after the guest is
healthy.
