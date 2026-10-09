---
description: Prettier's own guidance on pinning — install an exact version locally, because releases change formatting and an uninstalled npx run downloads the latest release.
---

# Prettier — Version Pinning

## What it is

Prettier's installation guidance on which Prettier a project should run.

## Guidance

- Install Prettier locally, at an **exact** version recorded in the project's
  `package.json`. Prettier states that even a patch release can change
  formatting, so different versions in different places reformat each other's
  output back and forth.
- When Prettier is not installed locally, `npx prettier` (and `bunx prettier`)
  temporarily downloads the **latest** release instead. Prettier calls this
  "not a good idea" because each release changes formatting. Running the local
  install is also faster.
- `pnpm exec prettier`, `yarn exec prettier`, and `npx prettier` with a local
  install all run the locally installed version.

## Sources

- https://github.com/prettier/prettier/blob/765aeba7cbf22277acadd0ab24a7a99744c9dd97/docs/install.md — installation guidance, the npx download warning, and the exact-version recommendation.
- https://prettier.io/docs/install — the published page for the same guidance.
