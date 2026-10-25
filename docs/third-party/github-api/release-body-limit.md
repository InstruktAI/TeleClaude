---
description: The GitHub Releases API rejects a release body over 125,000 characters; what is observed, what is documented, and how the length is counted.
---

# GitHub Release Body Limit

## Observed behavior

- Creating a release whose `body` exceeds the limit fails with HTTP 422
  `Validation Failed`, resource `Release`, field `body`, and the message
  `body is too long (maximum is 125000 characters)`.
- The limit is applied to characters, not encoded bytes. One reported failure
  measured 342,910 characters and 359,636 UTF-8 bytes, and the error quoted the
  character figure.
- No release is created when the body is rejected; the failure arrives only at
  the create call, after any earlier steps of a release flow have run.

## Documented behavior

- The Releases REST reference documents `body` as the release's description
  text for `POST /repos/{owner}/{repo}/releases`. It does not state a maximum
  length. The 125,000 figure is known from the API's own error message, not
  from the reference page.

## Counting semantics

- Whether "characters" means Unicode code points or UTF-16 code units is not
  documented. The two agree for text without characters outside the Basic
  Multilingual Plane; for astral characters (most emoji) the UTF-16 count is
  higher.
- Measuring in UTF-16 code units can only over-estimate the provider's count
  under either definition, so a body measured that way within 125,000 is
  accepted under both.

## Established handling

- A reference implementation keeps the complete notes in the repository's
  changelog and publishes a bounded body: it holds back a safety margin below
  the limit, cuts content on line boundaries (slicing a single line only when that
  line alone exceeds the remaining budget), states that the body is
  shortened, links to the complete entry in the changelog at the release's
  commit, and asserts the final body against the real limit before the call.

## Sources

- https://docs.github.com/en/rest/releases/releases#create-a-release
- https://github.com/intuit/auto/issues/2418
- https://raw.githubusercontent.com/objectstack-ai/objectstack/b0d3cb7/scripts/release-github-releases.mjs
