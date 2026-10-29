---
description: GitHub issue artifacts — the preview REST API for Markdown, HTML and link documents attached to an issue, with native version history, their limits, and the events they do not emit.
---

# GitHub Issue Artifacts

## What they are

- An issue artifact is a named document attached to one issue: a Markdown
  document (`generic` or `plan`), an HTML document (`embedded_html`) or a link
  (`link`). They are unrelated to GitHub Actions workflow artifacts.
- In the web UI an issue shows its artifacts beside the conversation, with an
  "Add artifact" action. Each artifact has its own page at
  `https://github.com/<owner>/<repo>/issues/<n>/artifacts/<number>`.
- `plan` currently behaves the same as `generic`. An `embedded_html` body is raw
  HTML source; GitHub renders a preview of it and escapes script in `body_html`.

## Maturity

- Private preview. Access is enabled per organization; a repository outside an
  enrolled organization does not serve the endpoints.
- The GitHub CLI calls the feature "in preview and subject to change without
  notice".
- The REST reference documents `X-GitHub-Api-Version: 2026-03-10`. Requests
  sent with `2022-11-28` were also served during verification.
- The REST reference lists `410 Gone` and `503` on every endpoint.

## REST endpoints

All paths are below `/repos/{owner}/{repo}/issues/{issue_number}/artifacts`.

| Method and path             | Purpose                                                                                           | Success                       |
| --------------------------- | ------------------------------------------------------------------------------------------------- | ----------------------------- |
| `GET` (collection)          | List artifacts in artifact-number order. Query: `type`, `per_page` (max 100, default 30), `page`. | `200`, array                  |
| `POST` (collection)         | Create. Body: `type` (default `generic`), `name` (required), `body` (required).                   | `201`, the artifact           |
| `GET /{artifact_number}`    | The artifact and its version history.                                                             | `200`, `{artifact, versions}` |
| `PATCH /{artifact_number}`  | Save a new version. Body: `name`, `body`, both optional.                                          | `200`, the artifact           |
| `DELETE /{artifact_number}` | Delete permanently.                                                                               | `204`                         |

- Documented error codes: `404`, `410`, `422` (validation failed or flagged as
  spam), `429` (throttled; retry after a delay), `500`, `503`.
- The artifact object carries `id`, `number`, `type`, `name`, `body`,
  `body_html`, `description` (derived text, present on a single-artifact read
  only), `creator`, `updated_by_actor`, `created_at`, `updated_at` and
  `html_url`. Each actor is `{login, id}` or null.
- A list response carries each artifact's current `body`.
- A version is `{version, name, body, body_html, created_at, actor}`.

## Permissions

- A GitHub App installation token with the repository `Issues` permission
  reaches the endpoints; no other permission exists for them. Reads answer
  `X-Accepted-GitHub-Permissions: issues=read; pull_requests=read`; create,
  update and delete answer `issues=write`.
- The REST reference states that creating, updating and deleting require
  permission to update the issue.

## Behavior verified against the API

Verified on 2026-10-28 with an App installation token and a user token on a
repository in an enrolled organization.

- **Numbering:** artifact numbers are sequential per issue, starting at 1.
- **Names:** names are not unique on an issue; two artifacts can carry the same
  name. Hyphenated lowercase names are accepted. The CLI documents that some
  characters, such as parentheses, are not allowed.
- **Type:** fixed at creation. A `PATCH` that sends `type` is refused with `422`.
- **Versions:** every successful `PATCH` saves a new version, including a rename
  without a body change. Version numbers increase per artifact, starting at 1.
- **Version attribution:** each version records the account that saved it; an
  App's versions carry its bot login (for example `instruktai[bot]`), a
  person's versions their own login. `creator` stays the first author and
  `updated_by_actor` names the last one.
- **Version history window:** `GET /{artifact_number}` returns at most the 30
  newest versions, newest first. `per_page`, `page` and other query parameters
  do not change that, and the response carries no `Link` header. Older versions
  are not reachable through the API.
- **Update response:** the `PATCH` response is the artifact object and does not
  carry the version number it saved; a following single-artifact read reveals
  it as the first entry of `versions`.
- **Size:** a 2 MiB body was saved by `POST` and `PATCH`; a 4 MiB body was
  refused with `500`. No limit is documented.
- **Conditional writes:** a `PATCH` with `If-Match` is refused with `400`
  ("Conditional request headers are not allowed in unsafe requests unless
  supported by the endpoint"). Reads return an `ETag`.
- **Conditional reads:** a list request sent with `If-None-Match` and the
  previous list's `ETag` answers `304 Not Modified` with no body while the
  issue's artifacts are unchanged; after an artifact is saved it answers `200`
  with the list and a new `ETag`.
- **Deletion:** anyone who may update the issue can delete any artifact,
  including one an App created. A deleted artifact and its history cannot be
  restored.
- **Restoring a version:** the API has no restore endpoint; the CLI's
  `--restore-version` saves an earlier version's name and content as a new
  version.

## Events

- No webhook event is emitted for creating, editing or deleting an artifact. A
  repository webhook subscribed to every event (`*`) received no delivery for
  any of the three, while it received the `issue_comment` delivery sent in the
  same window. The webhook events reference lists no artifact event, and the
  `issues` event has no artifact action.
- Artifact changes add no entry to the issue's timeline or events API and do not
  change the issue's `updated_at`.
- A change is therefore observable only by reading the artifacts: the list
  endpoint's `updated_at` and `updated_by_actor` per artifact, or a single
  artifact's versions.

## Pull requests

- Artifacts exist on issues only. GitHub's maintainers state that artifacts
  on pull requests are intended, without a timeline.

## Known gaps

- No GraphQL surface or GitHub MCP tool is documented.
- File uploads are not supported; image and video attachments are embedded
  through the CLI's `--attach` into the document body.
- No documented body size limit or rate limit specific to artifacts.

## Sources

- [REST API endpoints for issue artifacts](https://docs.github.com/en/rest/issues/artifacts)
- [Webhook events and payloads](https://docs.github.com/en/webhooks/webhook-events-and-payloads)
- [Issue Artifacts private preview feedback (community discussion)](https://github.com/orgs/community/discussions/205881)
- [GitHub CLI `gh issue artifact` client, v2.103.2](https://github.com/cli/cli/tree/v2.103.2/pkg/cmd/issue/artifact)
