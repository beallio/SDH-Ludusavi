# SDH-Ludusavi Notices and Attribution

This file records the project's source lineage and the third-party projects
whose code, APIs, documentation, or assets are used or referenced. Inclusion
here does not change any third party's license, imply endorsement, or mean that
an API-only integration is incorporated into SDH-Ludusavi.

## Project license

Project-authored SDH-Ludusavi source code is licensed under the MIT License.
Retained portions from decky-ludusavi and the Decky plugin template remain
subject to the BSD 3-Clause License. The applicable license texts and copyright
notices are in [LICENSE](LICENSE).

## Source and template lineage

### [GedasFX/decky-ludusavi](https://github.com/GedasFX/decky-ludusavi)

- **Role:** SDH-Ludusavi originally began as a fork of this Decky Ludusavi
  plugin and has since been substantially rewritten.
- **License:** BSD-3-Clause
- **Copyright:** 2024-2025 GedasFX

### [SteamDeckHomebrew/decky-plugin-template](https://github.com/SteamDeckHomebrew/decky-plugin-template)

- **Role:** Underlying template lineage shared with decky-ludusavi. Retained
  portions include the Decky plugin layout, build configuration, and type
  stubs.
- **License:** BSD-3-Clause
- **Copyright:** Steam Deck Homebrew

## Design inspiration

### [AkazaRenn/SDH-GameSync](https://github.com/AkazaRenn/SDH-GameSync)

- **Role:** The game-launch pause and pre-launch save-check concept was inspired
  by SDH-GameSync's approach of stopping a launching game while save data is
  synchronized, then resuming it.
- **Code use:** Conceptual attribution only; no SDH-GameSync code is bundled or
  claimed to have been copied.

### [suchmememanyskill/Steam-Deck-Themes: Clean Gameview](https://github.com/suchmememanyskill/Steam-Deck-Themes/tree/main/Clean%20Gameview)

- **Role:** Inspiration for the optional translucent Clean View status-bar
  appearance. The top-right icon relocation and full-page layout are not
  included.
- **Code use:** Original status-bar CSS; no upstream stylesheet is bundled.

## Vendored source

### [beallio/pyludusavi 0.3.0](https://github.com/beallio/pyludusavi)

- **Role:** Pure-Python Ludusavi adapter vendored under
  `py_modules/pyludusavi`.
- **License:** MIT
- **Full license:** `py_modules/pyludusavi-0.3.0.dist-info/licenses/LICENSE`

## Frontend dependencies and bundled icons

### [SteamDeckHomebrew/loader-api](https://github.com/SteamDeckHomebrew/loader-api) (`@decky/api` 1.1.3)

- **Role:** Frontend API dependency used by the generated plugin bundle.
- **License:** LGPL-2.1

### [SteamDeckHomebrew/decky-frontend-lib](https://github.com/SteamDeckHomebrew/decky-frontend-lib) (`@decky/ui` 4.11.0)

- **Role:** Frontend UI dependency used by the generated plugin bundle.
- **License:** LGPL-2.1

### [react-icons/react-icons 5.3.0](https://github.com/react-icons/react-icons)

- **License:** MIT; individual icon sets retain their upstream licenses.
- **Icon sets used:**
  - [Font Awesome](https://fontawesome.com/): CC BY 4.0
  - [Ionicons 4](https://github.com/ionic-team/ionicons): MIT

### [microsoft/tslib 2.8.1](https://github.com/microsoft/tslib)

- **License:** 0BSD

## Build tooling

### Project-owned Rollup configuration

- **Role:** Build-time configuration for the Decky frontend; not shipped as a
  standalone runtime package.
- **Source lineage:** Retains the Decky plugin template build contract while
  using direct Rollup plugins instead of the `@decky/rollup` preset.
- **Direct build dependencies:** `@rollup/plugin-commonjs`,
  `@rollup/plugin-json`, `@rollup/plugin-node-resolve`,
  `@rollup/plugin-replace`, `@rollup/plugin-typescript`,
  `rollup-plugin-external-globals`, and `rollup-plugin-import-assets`.
- **License:** MIT for the direct build dependencies. The BSD-3-Clause Decky
  template lineage remains attributed in the project-license section.

### [facebook/react: react-dom 18.3.1](https://github.com/facebook/react)

- **Role:** Development-only renderer for native status-row behavior tests; not
  bundled in the Decky plugin.
- **License:** MIT

### [WebReflection/linkedom 0.18.12](https://github.com/WebReflection/linkedom)

- **Role:** Development-only DOM for native status-row behavior tests; not
  bundled in the Decky plugin.
- **License:** ISC

## Runtime and API integrations

### [DeckThemes/SDH-CssLoader](https://github.com/DeckThemes/SDH-CssLoader)

- **Role:** Optional external CSS theme loader; not bundled or required for
  save operations.

### [SteamDeckHomebrew/decky-loader](https://github.com/SteamDeckHomebrew/decky-loader)

- **Role:** External plugin host and RPC runtime; not bundled.
- **License:** GPL-2.0

### [mtkennerly/ludusavi](https://github.com/mtkennerly/ludusavi)

- **Role:** External save-backup application invoked through its CLI; not
  bundled.
- **License:** MIT

### [syncthing/syncthing](https://github.com/syncthing/syncthing)

- **Role:** External synchronization service queried through its REST and event
  APIs; no Syncthing source code is bundled.
- **License:** MPL-2.0

### [zocker-160/SyncThingy](https://github.com/zocker-160/SyncThingy)

- **Role:** Optional external Flatpak recommended in the user documentation;
  not bundled and not required by SDH-Ludusavi.

## Artwork

The bundled Ludusavi shortcut artwork includes community assets obtained from
SteamGridDB. These images are not covered by the SDH-Ludusavi MIT license;
rights remain with their respective creators and rights holders.

- [Portrait capsule](https://cdn2.steamgriddb.com/grid/71c7ca74c4dec0da6247b49837c47ed5.png)
- [Hero image](https://cdn2.steamgriddb.com/hero/8e94f8d8e0d415f7ab0f35653eacd7f3.png)
