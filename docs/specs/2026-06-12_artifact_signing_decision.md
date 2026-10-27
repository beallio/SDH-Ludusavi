# Artifact Signing Decision

- **Status**: Deferred (decision recorded 2026-06-12).

## Current chain
The current verification chain is strong against tampered downloads. The manifest and ZIP share one trust root (the GitHub account). The implementation consists of:
- Manifest SHA-256 validation in `backend/src/updater.rs`.
- Asset-name pinning.
- Pre-install revalidation (`revalidate()` SHA-256 match).
- Hash handed to Decky's installer.

## Proposal considered
Use minisign/Ed25519 for artifact signing:
- Embed the public key in the native updater.
- Sign the manifest at release time (it contains the ZIP hash, so the artifact is transitively covered).
- Verify `manifest.minisig` in the updater before trusting anything.

## Why deferred (the honest costs)
1. At the time of the decision the backend was stdlib-only Python and had no
   Ed25519 primitive. The Rust cutover changes that implementation constraint;
   choosing and maintaining a verifier still requires a separate review.
2. The key only adds security if it lives OUTSIDE CI — a signing key in GitHub Actions secrets collapses back to account-equals-trust-root, so releases would gain a manual offline signing step.

## Revisit triggers
Revisit this decision if there is distribution outside the Decky Store at scale. This is partially moot if shipping through the store, due to its own review/distribution integrity.
