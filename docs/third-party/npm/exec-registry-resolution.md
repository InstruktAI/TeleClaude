---
description: When `npm exec` / `npx` contacts the registry — local-bin lookup first, otherwise an online-preferred manifest fetch even for a pinned version — and how `--offline` changes that.
---

# npm exec — Registry Resolution

## What it is

`npm exec` (and `npx`, its alias) runs a package's executable. Whether a given
invocation needs the npm registry is decided inside `libnpmexec` before
anything is installed or run. The behavior below is read from the `libnpmexec`
and `npm-registry-fetch` sources at the commits listed under Sources.

## A local executable short-circuits resolution

When the invocation names a command without a `--package` (`npx prettier ...`),
`libnpmexec` first looks for a matching executable:

- **A bin declared by the local project's own package.** That package is
  installed into the npx cache as a directory dependency, so its bin links
  exist.
- **An executable found walking up the `node_modules/.bin` directories** from
  the working directory, or in the global bin directory. It is executed
  directly. No manifest is fetched and no registry request is made.

## Without a local executable, resolution goes online

When no local executable is found, the requested spec is checked against the
local tree and then against the npx cache. Each check that cannot settle the
spec from the tree calls `pacote.manifest(..., { preferOnline: true })`:

- **Name-only spec** (`prettier`): a registry tag (`latest`). The tag must be
  resolved, so the manifest is fetched. In the npx cache, a name-only spec is
  checked explicitly for a newer published version.
- **Exact version spec** (`prettier@<version>`): if no node in the local tree
  has that exact package id, the manifest is fetched too.

So putting a version on the command line does not remove the registry
dependency. Only an executable already installed in the local tree, or on the
global bin path, does.

## Cache mode precedence

`npm-registry-fetch` maps the options to an HTTP cache mode in this order:
`offline` → only-if-cached; `preferOffline` → force-cache;
`preferOnline` → no-cache; otherwise default. `--offline` therefore overrides
the `preferOnline` that `libnpmexec` sets: the request is served from the local
cache or fails at once, and never touches the network. `--prefer-offline` uses
a cached entry without revalidating it, but still goes to the network on a
cache miss.

## Gaps

- No timeout behavior is documented for a registry connection that stalls
  mid-request. A stalled online fetch is not bounded by `libnpmexec` itself.

## Sources

- https://github.com/npm/cli/blob/b317f16c80df02ea3628cfa77170d5ae9b59720c/workspaces/libnpmexec/lib/index.js#L26-L84 — `getManifest` (`preferOnline: true`) and `missingFromTree`, including the name-only npx-cache freshness check.
- https://github.com/npm/cli/blob/b317f16c80df02ea3628cfa77170d5ae9b59720c/workspaces/libnpmexec/lib/index.js#L140-L192 — local package, `node_modules/.bin`, and global-bin lookup before any manifest resolution.
- https://github.com/npm/npm-registry-fetch/blob/6b4159a2519ce5aab26cc4dd8d4596a0b47781d2/lib/index.js#L207-L212 — `getCacheMode` precedence.
- https://docs.npmjs.com/cli/npm-exec/#a-note-on-caching — npm exec caching note.
