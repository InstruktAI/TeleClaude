# Input: deployment-versioning

## Context

Parent todo: `mature-deployment` (decomposed — too large for single session).
This is phase 1 of 5 in the automated deployment pipeline initiative.

## Brain dump

Currently TeleClaude has no proper versioning. `pyproject.toml` says `0.1.0` and
there's no way to query the version at runtime. No CI exists — no GitHub Actions
workflows at all. This todo establishes the foundation everything else depends on.

### Deliverables

1. **Semantic versioning** — bump pyproject.toml to a meaningful `1.0.0`, expose
   `__version__` at runtime via package metadata.

2. **`telec version` command** — prints current version, channel, and pinned minor
   (channel defaults to alpha until `deployment-channels` ships).

3. **CI pipeline** — GitHub Actions workflow that runs on push to main and PRs:
   `make lint` + `make test` with uv dependency caching.

4. **Release workflow** — GitHub Actions workflow triggered by version tags (`v*`)
   that creates a GitHub Release with changelog from commits since last tag.

### Why this first

Everything else in the deployment pipeline depends on version awareness:

- Channel subscription needs version comparison
- Migration runner needs version diffing
- Auto-update needs to know current vs available version
- CI provides the quality gate that makes automated deployment safe

### What exists today

- `pyproject.toml` with `version = "0.1.0"`
- No `__version__` exposed in the package
- No `telec version` command
- No `.github/workflows/` directory
- No GitHub releases or tags
