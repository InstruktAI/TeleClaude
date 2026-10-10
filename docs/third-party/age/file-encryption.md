---
description: age file encryption, native identities and recipients, authenticated payloads, and the distinction between integrity and sender identity.
---

# age file encryption

age is a maintained file-encryption tool with native identities and public
recipients. The CLI encrypts to a recipient and decrypts using a corresponding
identity. Its format authenticates the header and encrypted payload. Applications
use the tool or library rather than implementing the format's primitives.

Successful decryption establishes ciphertext integrity for the supplied identity.
It does not establish who produced the file, when it was produced, or whether it
is the latest version: anyone holding a public recipient can create a new valid
ciphertext for it. Producer authority and freshness are properties of the
surrounding storage protocol.

## Sources

- https://github.com/FiloSottile/age
- https://age-encryption.org/v1
- https://github.com/FiloSottile/age/blob/main/SIGSUM.md
