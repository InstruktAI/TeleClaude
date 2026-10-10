---
description: GitHub Actions secret injection timing, immutable artifact identity and retention, cross-run retrieval, and cancellation limits.
---

# Secret and artifact lifecycle

Repository and organization secrets are read when a workflow is queued;
environment secrets are read when their job starts. Updating a repository secret
during one run does not update the value already captured by another queued run.
The secrets API exposes metadata and update operations, not current plaintext
retrieval.

Actions artifacts have identities, producing-workflow metadata, expiration, and
download digests. Cross-run download is available through the artifact API with
Actions read access. Modern upload actions finalize immutable artifacts and
return their identity and digest. Artifact retention is bounded by repository
policy. A later workflow failure does not imply that its finalized artifacts are
absent.

GitHub's automatic artifact digest verification can report a mismatch as a
warning. Cancellation also imposes a bounded process shutdown; an `always()`
condition does not guarantee that a cleanup step survives runner loss or forced
termination.

## Sources

- https://docs.github.com/en/actions/reference/security/secrets
- https://docs.github.com/en/rest/actions/artifacts
- https://docs.github.com/en/actions/tutorials/store-and-share-data
- https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-cancellation
- https://github.com/actions/upload-artifact
