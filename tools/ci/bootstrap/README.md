# Fresh machine bootstrap harness

This harness launches a disposable macOS VM with Tart, installs the checkout
from its committed Git bundle, checks startup and documentation publication,
then reports role and identity probes. It always attempts to stop and delete
the VM. Run it with `uv run python -m tools.ci.bootstrap` from the repository
root.

The runner requires a macOS host, the Tart version checked by the command, and
the documented platform prerequisites in the base image. Use `--base-image`,
`--vm-name-prefix`, and `--output-dir` to change the VM image, its temporary
name prefix, or where the run report and collected logs are written.

The seed files contain only `.invalid` addresses. The owner seed is supplied
to the guest install through the install-only environment inputs. The people
seed drives the configuration and access-scope probes after the guest is
healthy.
