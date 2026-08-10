# Issues to import when tracked upstream

Status: Local backlog

The IDs below are stable local references. When imported into a forge, replace each
`#N` dependency with the created issue link. Hardware verification remains required
where noted.

## #1 Establish which device the plugin log path was verified on

- Dependencies: None
- User impact: Low today, but it decides whether log-path handling can be shared. If the
  path was only ever confirmed on one device, tooling that assumes it holds everywhere
  will fail on the other.
- Technical approach: The project memory recording the live plugin log location
  (`/home/deck/homebrew/logs/SDH-Ludusavi`) introduces it as "On the Steam Deck
  (`ssh steamdeck-legos`)". Those are two different machines: `steamdeck` is the Steam
  Deck and `steamdeck-legos` is a Legion Go S. Both run SteamOS, so the path plausibly
  holds on both, but the note as written cannot tell you which one it was actually
  observed on. Re-confirm the log root on each device and record the device alongside the
  finding. While there, confirm whether the directory name is keyed off the plugin's
  `plugin.json` name or its folder name, since that determines whether a renamed plugin
  moves its logs.
- Security/privacy: None. Read-only inspection.
- Unit tests: None applicable — this is a device-provenance question, not code.
- Hardware tests: Required, on both devices. Read-only: list the log root on each and
  record which device produced which result.
- Acceptance: The log root is recorded per device, and any shared tooling that resolves a
  log path takes the device as a parameter rather than assuming the Deck's layout.
- Provenance: Found 2026-07-26 by the decky-tooling Phase 1 memory harvest; recorded as a
  contradicted row in `../decky-tooling/docs/harvest/knowledge-ledger.md`. The underlying
  memory has since been corrected to name the device conflation, but the measurement it
  records still has unknown provenance.
