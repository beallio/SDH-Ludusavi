# Steam-Native Status Presentation

## Problem Definition

The Ludusavi Game Details row uses heavier text, left-aligned content, a dark background, semantic red/amber/blue text colors, and long messages such as `Current activity: Backing up local save`. Steam's native Cloud row uses a centered 30 px band, compact `Service: Status` wording, Motiva Sans uppercase text, subdued white text, blue active-transfer text, balanced divider lines, and a translucent problem background.

The Ludusavi row must use Steam's presentation language without claiming that a local backup proves remote synchronization. Detailed local and remote guarantees remain in the accessible description.

## Architecture Overview

Only the native Game Details row changes. The protected BrowserView launch strip, lifecycle operations, ownership arbitration, timers, native Steam Cloud exclusion, and state selection remain unchanged.

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

1. Add failing model tests for compact Steam-style visible messages while retaining detailed local/remote descriptions.
2. Add a failing native-row presentation test for centered layout, measured typography, Steam colors, divider behavior, and active icon pulse.
3. Implement the smallest model and row changes that pass those tests.
4. Run the focused frontend tests, TypeScript check, and production build through `./run.sh`.
5. Run the complete project quality gates.
6. Install a local development ZIP on the Deck and visually confirm the centered row, font, colors, status wording, native Cloud exclusion, and clean reload behavior.
