# Steam-Native Status Presentation

## Problem Definition

The Ludusavi Game Details row uses heavier text, left-aligned content, a dark background, semantic red/amber/blue text colors, and long messages such as `Current activity: Backing up local save`. Steam's native Cloud row uses a centered 30 px band, compact `Service: Status` wording, Motiva Sans uppercase text, subdued white text, blue active-transfer text, balanced divider lines, and a translucent problem background.

The Ludusavi row must use Steam's presentation language without claiming that a local backup proves remote synchronization. Detailed local and remote guarantees remain in the accessible description.

The persisted operation history already retains a skipped operation's reason, but the native row
currently discards that reason after reload. As a result, a live `local_current` skip appears as
`Up to date`, while the same durable last operation appears as `Unknown`. The live and durable
paths must classify the same terminal result consistently.

`Unknown` also currently inherits warning styling, which removes the normal dividers and adds the
translucent problem background. Steam does not present its unknown Cloud state as a problem state,
so the Ludusavi row must use the normal transparent, divided treatment for `Unknown`.

## Architecture Overview

The native presentation stays unchanged. Terminal operation-result classification is shared by
the live status surface and the durable Game Details selector so a reload cannot change the
meaning of the same result. The protected BrowserView launch strip, lifecycle operations,
ownership arbitration, timers, native Steam Cloud exclusion, and selection precedence remain
unchanged.

The row will:

- retain the `Ludusavi:` service prefix;
- show a compact Steam-style status value;
- center the icon and label as one group;
- use equal divider lines on both sides for normal states;
- use Steam's measured native typography and base colors;
- use Steam blue for active transfer text;
- use a translucent problem background and omit dividers for warning/error states;
- pulse the active icon like Steam instead of rotating it.

## Core Data Structures

`GameDetailsStatusViewModel` remains the semantic source for status, tone, activity, visible label, and detailed accessible description.

Visible status mappings:

- checking and pending remote work: `Checking...`
- local backup: `Backing up...`
- local restore: `Restoring...`
- remote upload/download: `Uploading...` / `Downloading...`
- current or completed local/remote result: `Up to date`
- missing first backup: `Out of sync`
- conflict: `File conflict`
- failed or unavailable synchronization: `Unable to sync`
- disabled synchronization: `Disabled`
- unknown result: `Unknown`

The accessible description continues to distinguish local backup state from observed or unverified remote state.

`Unknown` uses the normal informational tone. It does not use warning/problem presentation.

Terminal result classification:

- `backed_up`, `restored`, or `skipped/local_current`: `has_backup` → `Up to date`;
- `conflict` or `skipped/conflict_unresolved`: conflict state → `File conflict`;
- disabled skip reasons: `game_sync_disabled` → `Disabled`;
- failures and error-class skip reasons: error state → `Unable to sync`;
- other skipped results: unknown state → `Unknown`.

The durable selector consumes the recorded `last_operation.reason`; it does not reduce a persisted
operation from `status` alone.

## Public Interfaces

No backend, RPC, event, persistence, or Steam API interface changes.

The existing `GameDetailsStatusViewModel.label` contract changes from a verbose category-prefixed sentence to `Ludusavi: <compact status>`. `description` retains detailed provenance and limitations.

The native row remains non-interactive and adds no controller focus stop.

## Dependency Requirements

There are no runtime dependency changes. The pre-commit supply-chain audit required the
development-only Vitest patch from 4.1.8 to 4.1.11, which contains the fix for its current
moderate-severity path-traversal advisory.

Measured Steam reference values from the live Deck:

- row: 30 px high, flex centered, `padding: 4px 0`;
- label: `Motiva Sans`, 12 px, weight 700, line-height 22 px, letter-spacing 0.5 px, uppercase;
- normal label: `rgba(255, 255, 255, 0.7)`;
- active upload/download value: `#1a9fff`;
- dividers: `rgba(61, 68, 80, 0.54)`, 2 px high;
- problem background: `rgba(255, 255, 255, 0.16)`;
- active icon pulse: 1.5 seconds toward `#3d4450`.

## Testing Strategy

1. Add a failing reload regression proving that durable `skipped/local_current` stays `Up to date`
   and retains the detailed `Local save already current` description.
2. Add a failing model regression proving that `Unknown` uses the normal informational tone.
3. Route both live and durable terminal results through one pure classification function.
4. Run the focused frontend tests, TypeScript check, and production build through `./run.sh`.
5. Run the complete project quality gates.
6. Install a local development ZIP on the Deck and verify the result remains `Up to date` after a
   clean plugin reload.
