//! Verify the public API forces external callers to go through
//! [`identity::Principal::resolve_anonymous`] rather than constructing
//! `Principal::Anonymous` directly.
//!
//! Integration tests live in a separate crate from the library, so they
//! exercise the `#[non_exhaustive]` boundary the production callers see.
//! A `trybuild` ui-test would be the most precise tool, but the existing
//! workspace doesn't pull `trybuild` in; this single positive test plus
//! the compile-fail snippet below (kept commented because it must fail
//! to compile) document the contract.

use identity::Principal;

#[test]
fn external_callers_can_construct_anonymous_via_resolve_anonymous() {
    let anonymous = Principal::resolve_anonymous();
    // Pattern-match via the wildcard: `#[non_exhaustive]` blocks direct
    // construction AND direct unit-variant patterns from external crates,
    // so the only legal check here is a typed-not-other-variant assertion.
    let is_anonymous = matches!(
        anonymous,
        Principal::Human { .. } | Principal::AgentSession { .. } | Principal::System { .. }
    );
    assert!(
        !is_anonymous,
        "resolve_anonymous() must yield the Anonymous variant"
    );
}

// Compile-fail evidence — leave commented; uncomment locally to confirm
// the `#[non_exhaustive]` shield is active.
//
//   let _shielded = Principal::Anonymous;
//
// rustc rejects with: cannot construct `Principal::Anonymous` because it
// has a private field / `#[non_exhaustive]` is set in identity.
