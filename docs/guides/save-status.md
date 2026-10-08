# Understand your save status

SDH-Ludusavi shows what it knows about your game saves in two places. The row on a supported non-Steam game's page shows the latest known result. A separate message appears while the plugin checks saves before a game starts. After you quit, the full post-game message appears only on the affected game's page, either in its normal row or in a same-page fallback when the row cannot be used. The game-page row is for information only; use the Decky menu to change settings or choose a backup.

Steam Cloud games keep their Steam Cloud status. The Ludusavi row does not replace Steam Cloud or change which games the plugin can back up.

By default, the Ludusavi row uses the same layout as Steam's Cloud row. Its save-status icons remain easy to tell apart, but use the row's normal size and alignment. A transparent area of the footer does not hide a message that remains readable in the normal row. If the full message is genuinely covered or clipped, the plugin uses the same-page fallback instead. The post-game fallback also uses Steam-style text, colors, side lines, and icon pulse, while keeping the full message. The game-launch strip keeps its separate appearance. The plugin does not move the row or force the page to scroll.

## What the game-page row means

| Status | What it tells you | What to do |
| --- | --- | --- |
| **Checking**, **Backing up**, or **Restoring** | Save work is in progress. | Wait for it to finish before you act on the save. |
| **Up to date** | A local backup is available, a recent local save check succeeded, or the plugin observed a remote result. It does **not** mean every other device has your save. | If you use another device, check Syncthing there too. |
| **Out of sync** | Ludusavi has not made the first backup for this game. | Open SDH-Ludusavi in Decky, select the game, and choose **Force Backup**. |
| **File conflict** | The plugin cannot safely decide which save to use. | Read the choice shown before the game starts. Choose the save you want to keep; do not guess if you are unsure. |
| **Disabled** | Automatic Sync is off globally or for this game. | Check **Automatic Sync** and **Sync This Game** in the Decky menu if you want automatic checks and backups. |
| **Not tracked** | Ludusavi does not recognize this game. | Check the game in Ludusavi, then choose **Refresh Games** in the plugin. |
| **Unknown** | There is not enough recent information to say what happened. | Check the game in the Decky menu or refresh the game list. |
| **Unable to sync** | A local save operation or a check of Syncthing had a problem. | Read the extra text below the status. A remote warning does not necessarily mean the local backup failed. Open **View Logs** in the plugin if you need help. |

The row can include more detail about the **local result** and a **remote observation**. A local backup is a copy on this Deck. A remote observation is what the plugin saw Syncthing do with the backup folder. It cannot confirm that an offline device has received anything. After a plugin reload, an earlier remote result may be unverified until there is a new observation.

## What you may see when you start or quit a game

- **VERIFYING GAME SAVE**: The plugin is checking before it decides whether to restore a backup or make a new one.
- **RESTORING BACKUP SAVE**: A newer backup is being restored before the game starts.
- **BACKING UP LOCAL SAVE**: Ludusavi is making a backup after you quit.
- **GAME SAVE UP TO DATE**: The current check or save operation finished. This message alone is not proof that another device has your save.
- **SAVE CONFLICT**: The plugin is waiting for you to choose between the local save and the backup. If you dismiss the choice, it does not silently choose one for you.
- **SAVE SYNC DISABLED FOR THIS GAME**: This game is excluded from automatic backup and restore while global Automatic Sync is on. Manual backup and restore are still available.
- **SYNCTHING DOWNLOADING** or **SYNCTHING UPLOADING**: The plugin has seen activity or is waiting to confirm that the shared backup folder has settled. An uploading label does not tell you how many bytes moved.
- **SYNCTHING COMPLETE**: Before a game starts, incoming changes to the shared folder have settled on this Deck. After a backup, the plugin has seen at least one connected device catch up. It does not confirm that every device has the backup.
- **LOCAL BACKUP SAVED - PATH NOT SHARED**: The backup was made on this Deck, but Syncthing is not sharing its backup folder with another device.
- **LOCAL BACKUP SAVED - NO SYNCTHING PEERS ONLINE**: The local backup was made, but no device sharing that folder was connected at the time.
- **LOCAL BACKUP SAVED - SYNCTHING UPLOAD INCOMPLETE**: The local backup was made; the plugin could not confirm a completed transfer before it stopped watching. Syncthing may still finish later.
- **LOCAL BACKUP SAVED - SYNCTHING UNAVAILABLE**: The local backup was made, but the plugin could not check Syncthing.
- **UNABLE TO SYNC**: The save check or operation failed or could not continue safely. Look at **View Logs** if it happens again.

After you quit, leave the affected game page to hide its post-game message. This does not stop a backup or Syncthing observation. If you return while work continues, the page shows the latest state without starting it again. Upload activity replaces the local-success message as soon as the plugin observes it. If work finished, the row keeps the latest local result and remote observation even after the short fallback message expires. The fallback does not get a new lifetime when you return.

You can check the latest known result on the game page, but a past message does not replace a check on the other device. If a game page has no Ludusavi row after the plugin reloads, open another page and return. The plugin keeps the original game-page positions instead of moving the Play controls or status row to fit a message. Artwork can cover the status area without changing that layout. If the footer or a theme covers, clips, or cannot fit the row, the fallback stays on that same game page. You can still use the plugin from Decky.

For help with sharing backups, see [Set up Syncthing](syncthing.md). Return to the [main README](../../README.md) for installation and first use.
