---
description: Maintainer-provided git-cliff action inputs, file outputs and command construction.
---

# git-cliff action

The maintainer-provided composite action accepts a tool version, configuration
path and CLI arguments. It downloads the requested git-cliff binary and exposes
the generated file path, content and version as step outputs. A complete Git
history checkout is documented as its prerequisite.

The composite action interpolates configuration and argument inputs into its
shell invocation. Its wrapper forwards the resulting arguments to git-cliff,
renders a context file, emits the output file content when within its own size
bound and reports the file path. Its content output is not the sole carrier of
the generated file. Action and tool versions are separate selections.

## Sources

- https://github.com/orhun/git-cliff-action
- https://github.com/orhun/git-cliff-action/blob/a9a95522b26fe6403f7bb24031f21fb573d0f5ff/action.yml
- https://github.com/orhun/git-cliff-action/blob/a9a95522b26fe6403f7bb24031f21fb573d0f5ff/run.sh
