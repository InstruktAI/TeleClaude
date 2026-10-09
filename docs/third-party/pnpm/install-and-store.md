---
description: pnpm install semantics a pinned tool install relies on — frozen-lockfile failure, store hard links shared across projects, and symlinked node_modules resolving to their target.
---

# pnpm — Install and Store

## What it is

`pnpm install` installs a project's dependencies from `package.json` and
`pnpm-lock.yaml` into the project's `node_modules`, with package files kept in a
machine-wide content-addressable store. The behavior below is from the pnpm
documentation and source at the revisions listed under Sources.

## Frozen lockfile

With `frozenLockfile` set (`pnpm install --frozen-lockfile`), pnpm does not
write `pnpm-lock.yaml`, and it fails the installation when the lockfile needs
updating to satisfy the manifest. The setting defaults to false outside CI.
In CI it defaults to true when a lockfile is present.

## Content-addressable store

Each package version's files are stored once in the store. An install
hard-links them from the store into the project's `node_modules`. Several
projects, or several checkouts of one project, that install the same version
share the stored files without copying them. Each still gets its own
`node_modules` tree, built from its own lockfile.

## A symlinked node_modules is resolved to its target

pnpm resolves the root modules directory and each project's modules directory
through `realpathMissing` before installing. When a project's `node_modules`
is a symlink to another directory, pnpm installs into the symlink's target,
not into a new directory beside the project. Running `pnpm install` in a
checkout whose `node_modules` links to another checkout's therefore changes
the other checkout's installed tree.

## Sources

- https://github.com/pnpm/pnpm.io/blob/caf7a332ed85d158fdbcbec6f7c3224b32b4e27d/docs/settings/store.md — `frozenLockfile` defaults and failure behavior.
- https://github.com/pnpm/pnpm.io/blob/caf7a332ed85d158fdbcbec6f7c3224b32b4e27d/docs/cli/install.md — `pnpm install` and `--frozen-lockfile`.
- https://github.com/pnpm/pnpm.io/blob/caf7a332ed85d158fdbcbec6f7c3224b32b4e27d/docs/motivation.md — content-addressable store and hard links.
- https://github.com/pnpm/pnpm/blob/v10.30.0/pkg-manager/read-projects-context/src/index.ts — `realpathMissing` resolution of the root and per-project modules directories.
