## Core Steam Cloud status labels

These are the English Steam client / SteamOS-facing variants I found:

| Situation                            | User-facing status               |
| ------------------------------------ | -------------------------------- |
| Unknown cloud state                  | `Unknown`                        |
| Cloud disabled                       | `Disabled`                       |
| Synced                               | `Up to date`                     |
| Checking cloud state                 | `Checking...`                    |
| Local device needs cloud changes     | `Out of sync`                    |
| Another device has not uploaded yet  | `Out of sync`                    |
| Upload in progress                   | `Uploading...`                   |
| Upload in progress with percentage   | `Uploading... (%1$s%)`           |
| Download in progress                 | `Downloading...`                 |
| Download in progress with percentage | `Downloading... (%1$s%)`         |
| Sync failure                         | `Unable to sync`                 |
| Conflict detected                    | `File conflict`                  |
| Launch-time cloud step               | `Synchronizing cloud`            |
| Broader display status               | `Synchronizing with Steam Cloud` |

Valve’s 2022 client update notes that the Library and App Details surfaces show cloud status, a cloud status icon, progress percentage while syncing, and manual retry when sync fails. ([Steam Store][3]) The above strings are present in the current English Steam UI localization extraction. ([GitHub][2])

## Tooltip / explanatory variants

Steam may also show explanatory text for those statuses:

| Status                                | Meaning shown to user                                      |
| ------------------------------------- | ---------------------------------------------------------- |
| Disabled                              | Steam Cloud sync is disabled for the app                   |
| Up to date                            | Steam Cloud files are synchronized                         |
| Checking                              | Checking cloud status                                      |
| Out of sync, pending download         | Cloud changes have not downloaded to this device           |
| Out of sync, pending upload elsewhere | Another device has changes not yet uploaded                |
| Uploading                             | Uploading to Steam Cloud                                   |
| Downloading                           | Downloading files from Steam Cloud                         |
| Unable to sync                        | Error synchronizing files; user can click to retry         |
| File conflict                         | Files conflict with Steam Cloud versions; user can resolve |

These tooltip variants are listed beside the cloud status labels in the Steam UI localization. ([GitHub][2])

## Conflict dialog variants

When local save data conflicts with Steam Cloud, the dialog uses:

| Element                       | User-facing text / variant                            |
| ----------------------------- | ----------------------------------------------------- |
| Header                        | `Cloud Conflict`                                      |
| Remote choice                 | `Cloud Save`                                          |
| Local choice                  | `Local Save`                                          |
| Recency marker                | `Newer`                                               |
| Recency marker                | `Older`                                               |
| Modified timestamp            | `Modified %1$s`                                       |
| Unknown timestamp/state       | `Unknown`                                             |
| Footer, launch flow           | selection required before launch                      |
| Local-save choice explanation | cloud save will be overwritten by this device’s files |
| Cloud-save choice explanation | local save will be overwritten by Steam Cloud files   |

The longer conflict body tells the user that local save data conflicts with Steam Cloud and that the unchosen version will be overwritten. ([GitHub][2])

## Sync-failure dialog variants

When Steam cannot sync saves:

| Context             | Header           | Action buttons          |
| ------------------- | ---------------- | ----------------------- |
| Launch-time failure | `Unable to Sync` | `Play anyway`, `Cancel` |
| Retry flow          | `Unable to Sync` | `Retry Sync`, `Cancel`  |

The launch-time warning says Steam could not sync the game’s saves with Steam Cloud and warns that playing may lose previous progress. The retry-flow version says Steam was recently unable to sync and offers another sync attempt. ([GitHub][2])

[1]: https://partner.steamgames.com/doc/features/cloud "Steam Cloud (Steamworks Documentation)"
[2]: https://raw.githubusercontent.com/SteamTracking/SteamTracking/refs/heads/master/ClientExtracted/steamui/localization/steamui_english.json "raw.githubusercontent.com"
[3]: https://store.steampowered.com/news/125571/ "News - Steam Client Update Released"
