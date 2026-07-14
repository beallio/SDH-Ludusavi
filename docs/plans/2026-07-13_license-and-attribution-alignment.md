# License and Attribution Alignment

## Problem Definition

The repository currently declares `GPL-3.0-only`, even though its retained template code is
BSD-3-Clause and its original project-authored code and vendored `pyludusavi` dependency were
published under MIT. The release archive also omits a consolidated notice identifying source
lineage, bundled third-party code, runtime integrations, and artwork provenance. Public
documentation still contains a stale `v0.2.3` installation URL.

## Architecture Overview

Keep licensing responsibilities separated by role:

- license project-authored SDH-Ludusavi code under MIT;
- retain the BSD-3-Clause notices for decky-ludusavi and the Decky plugin template in `LICENSE`;
- record SDH-GameSync as design inspiration for the game-launch pause and pre-launch save check,
  without implying that its code is bundled;
- preserve the vendored pyludusavi MIT license in its dist-info directory;
- describe bundled frontend libraries and API-only integrations in `NOTICE` without claiming
  ownership or relicensing them;
- include `NOTICE` in source and Decky release artifacts.

## Core Data Structures

No runtime data structures change. The authoritative legal/documentation surfaces are:

- `LICENSE`: project MIT terms followed by the retained decky-ludusavi and Decky template
  BSD-3-Clause terms;
- `NOTICE`: repository URLs, roles, versions where pinned, licenses, and bundled/non-bundled
  status;
- `package.json` and `pyproject.toml`: project license metadata;
- packaging required-file lists: artifact inclusion and validation of `NOTICE`.

## Public Interfaces

No RPC or UI interfaces change. Public-facing changes are the README installation example,
license summary, attribution link, and the contents of source/release archives.

## Dependency Requirements

No dependencies are added or upgraded. License assertions are verified from repository history,
vendored metadata, installed package metadata, and authoritative upstream repositories.

## Testing Strategy

1. Add regression assertions requiring `NOTICE`, MIT project metadata, and notice inclusion in
   generated/validated Decky ZIPs.
2. Run the focused protocol and packaging tests to confirm they fail before implementation.
3. Update licensing, documentation, packaging, and validation surfaces.
4. Run focused tests, formatting/static checks, the full Python suite, frontend verification,
   and `git diff --check`.
