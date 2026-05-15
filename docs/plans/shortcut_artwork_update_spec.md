# Specification: Ludusavi Shortcut Asset Management Update

## Objective
Update the visual identity of the Ludusavi shortcut created by the Decky plugin by refreshing the hero and portrait artwork and removing the logo overlay.

## Background
The Ludusavi shortcut currently uses a set of static assets bundled with the plugin. Feedback suggests that the logo overlay is redundant or unappealing, and the hero and portrait images need updating to better match the project's branding.

## Requirements

### 1. Asset Removal
- **Logo Overlay**: The `logo.png` asset must be removed from the project.
- **Logo Application Logic**: The code responsible for applying the logo and setting its position (bottom-left) must be removed.

### 2. Asset Updates
- **Portrait Capsule (`grid_p.png`)**: Replace with the image from [SteamGridDB](https://cdn2.steamgriddb.com/grid/71c7ca74c4dec0da6247b49837c47ed5.png).
- **Hero Image (`hero.png`)**: Replace with the image from [SteamGridDB](https://cdn2.steamgriddb.com/hero/8e94f8d8e0d415f7ab0f35653eacd7f3.png).
- **Wide Capsule (`grid_l.png`)**: No changes required. The existing asset should be preserved and continue to be applied.

### 3. Technical Constraints
- All assets must remain in PNG format.
- Assets must be bundled within the plugin at build time; no external network requests are allowed during shortcut creation.
- The `SetCustomArtworkForApp` SteamClient API must continue to be used for application.

## User Interface Impact
- The Ludusavi shortcut in the Steam library will now display the new hero and portrait artwork.
- The logo overlay will no longer appear over the hero image.
- The wide capsule (landscape view) remains unchanged.

## Verification Criteria
- `assets/steamgrid/ludusavi/logo.png` is deleted.
- `assets/steamgrid/ludusavi/grid_p.png` and `hero.png` match the new sources.
- `src/shortcutArtwork.ts` no longer contains logo positioning or application logic.
- Automated tests in `tests/test_shortcut_artwork_static.py` are updated to reflect the removal of the logo.
