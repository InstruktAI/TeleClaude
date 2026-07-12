---
description: mcp-remote proxy CLI surface and its header env-var interpolation
  contract, verified against the shipped 0.1.38 package source.
---

# mcp-remote — Header interpolation

## What it is

`mcp-remote` is the npm proxy that bridges a stdio MCP client to a remote HTTP/SSE MCP server. TeleClaude's daemon spawns it via `npx` for every remote server lease, passing the server URL, `--header` arguments, and a `--transport` flag.

## CLI surface used by TeleClaude

- `npx -y mcp-remote@<version> <server-url> [--header "Name: value"]... --transport <sse-only|http-only>`
- Each `--header` argument carries one `Name: value` pair. Values may reference environment variables (see below).

## Header env-var interpolation contract (verified 0.1.38)

- Before connecting, mcp-remote rewrites every parsed header value with `value.replace(/\$\{([^}]+)}/g, …)`, substituting `process.env[<name>]` for each match (shipped source: `dist/chunk-65X3S4HB.js:20851`, v0.1.38).
- **Only the braced `${VAR}` form is substituted.** A bare `$VAR` reference is passed through as literal text. An operator form such as `${VAR:-fallback}` is looked up as the literal env name `VAR:-fallback` — shell-style operator semantics are not implemented.
- A referenced variable missing from the proxy's environment substitutes to the **empty string** and logs a warning; mcp-remote does not fail the connection for it.
- Header pairs are logged (`Using custom headers: <json>`) **before** substitution, so placeholder text — never resolved secrets — appears in the proxy's own log output.
- The README (§Custom Headers) documents this shape as the sanctioned way to keep tokens out of client config: placeholder in `args`, real value in the child `env`.

## Known gaps

- The interpolation is not documented as a stable API contract by upstream; it is README-documented behavior verified against the shipped 0.1.38 bundle. A version bump must re-verify the substitution regex before trusting it as a security boundary.
- OAuth session storage keys on the combination of URL and custom headers; changing header text invalidates prior sessions.

## Sources

- https://github.com/geelen/mcp-remote — upstream repository (README §Custom Headers).
- https://www.npmjs.com/package/mcp-remote — published package (0.1.38 verified locally from the npx cache: `dist/chunk-65X3S4HB.js:20851`).
