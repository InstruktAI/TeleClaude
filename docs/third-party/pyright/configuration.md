---
description: Pyright configuration path resolution, execution-environment matching, and diagnostic overrides.
---

# Pyright Configuration

## Configuration and path resolution

- `pyrightconfig.json` is the project configuration file. When it and a
  `[tool.pyright]` table are both present, the JSON file takes precedence.
- Relative paths in a configuration file resolve from that file's directory.
  This includes included source paths and inherited configuration paths.
- `include` accepts directory or file paths. Excluded files may still enter
  analysis when an included source imports them.

## Execution environments

- Execution environments are evaluated in declaration order. Each source file
  uses at most one environment: the first environment whose root contains it.
- An environment may override import search paths, Python version and platform,
  and any type-check diagnostic setting for files mapped to that environment.
- Environment-local `extraPaths` replaces the top-level `extraPaths` for import
  resolution in that environment. Imported files resolve their own imports
  using the environment mapped to those files.

## Diagnostic configuration

- `typeCheckingMode` selects the default rule set. Individual diagnostic rules
  can override that mode with boolean values or the severities `none`,
  `warning`, `information`, and `error`.
- `reportArgumentType` controls diagnostics for argument incompatibilities at
  call expressions. Its documented strict-mode default is `error`.
- Per-environment diagnostic settings act as overrides for files mapped to that
  environment, allowing a bounded subtree to carry a different severity while
  the repository default remains strict.

## Documented gap

The configuration reference defines an execution-environment root as a path for
the code in that environment and documents containment-based matching. It does
not separately specify whether a regular file path is accepted as a root.

## Sources

- https://github.com/microsoft/pyright/blob/main/docs/configuration.md
