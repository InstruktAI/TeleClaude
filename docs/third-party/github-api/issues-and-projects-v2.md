---
description: GitHub Issues, Projects v2, native issue dependencies, and sub-issues API primitives used by the todo mirror's projector — accessed via gh, validated against the live API.
---

# GitHub Issues & Projects v2 API — Mirror Primitives

The todo mirror's projector asserts GitHub state through these primitives, accessed with the
machine's `gh` login (`gh api` for REST, `gh api graphql` for GraphQL; scopes `repo` + `project`).
Every primitive below was validated end-to-end against a throwaway repository via the local `gh`
token before this was recorded; the authoritative references are in Sources. Exact request/response
payload shapes are confirmed against the cited docs at build time.

## Issues (REST)

- **Create / update:** `POST /repos/{owner}/{repo}/issues`, `PATCH /repos/{owner}/{repo}/issues/{number}`.
  The issue body carries the mirror's hidden identity marker as an HTML comment
  (`<!-- ... -->`), invisible when rendered and recoverable by scanning the body.
- **State mapping:** an issue has `state` (`open` | `closed`) and `state_reason`
  (`completed` | `not_planned` | `reopened`). The mirror maps todo status to:
  open (active/icebox), **closed + `completed`** (delivered → closed-completed), and
  **closed + `not_planned`** (removed → closed-not-planned). Reopen sets `state: open`.
- **Marker scan:** the local→GitHub index is reconstructible by listing issues and reading the
  marker out of each body; no server-side custom field is required for identity.

## Projects v2 (GraphQL only)

Projects v2 has **no REST surface** for field provisioning or item field values — it is GraphQL.

- **Create board:** `createProjectV2`.
- **Single-select fields + options:** `createProjectV2Field` defines a single-select field and its
  option set (the mirror's Kind / Phase / Hold values). Option ids are **server-generated** and must
  be read back and cached (rebuildable) to set values later.
- **Add an issue as a board item:** `addProjectV2ItemById` (takes the issue's **node id**).
- **Set an item's field value:** `updateProjectV2ItemFieldValue` (single-select takes the
  server-generated option id). This is the reliable path for setting item values; the option lists
  themselves are provisioned once via `createProjectV2Field`.

## Native issue dependencies — "blocked by" (REST)

- **List / add / remove** the blocked-by set:
  `GET|POST|DELETE /repos/{owner}/{repo}/issues/{number}/dependencies/blocked_by`.
- The add payload identifies the blocking issue by its **database integer id** (not the node id).
- **Read-then-reconcile:** read the current blocked-by edges, then apply only the diff to match the
  todo's `after` set. A blind re-add of an existing edge returns **HTTP 422** — treat 422 as
  already-converged, not an error.

## Native sub-issues — parent / child (REST)

- **List / add:** `GET|POST /repos/{owner}/{repo}/issues/{number}/sub_issues`.
- The add payload identifies the child by **`sub_issue_id` = the child issue's database integer id**
  (not the node id).
- Same read-then-reconcile discipline: a re-add of an existing parent/child edge returns **HTTP 422**,
  treated as already-converged.

## Identity quirk (load-bearing)

Two id spaces coexist: the **node id** (used by the Projects v2 GraphQL surface) and the **database
integer id** (used by the dependencies and sub-issues REST surfaces). The projector keeps both for a
mirrored issue and uses the right one per call.

## Access & scopes

- REST via `gh api <path>`; GraphQL via `gh api graphql -f query=...`.
- Required `gh` token scopes: **`repo`** and **`project`**. `make install` verifies these and prints
  `gh auth refresh -s <missing>` for any gap; no token is stored in `teleclaude.yml`.

## Sources

- https://docs.github.com/en/rest/issues/issues
- https://docs.github.com/en/rest/issues/issue-dependencies
- https://docs.github.com/en/rest/issues/sub-issues
- https://docs.github.com/en/graphql/reference/mutations
- https://docs.github.com/en/issues/planning-and-tracking-with-projects/automating-your-project/using-the-api-to-manage-projects
- https://cli.github.com/manual/gh_api
