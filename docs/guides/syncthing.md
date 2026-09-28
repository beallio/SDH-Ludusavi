# Set up Syncthing for your backups

SDH-Ludusavi makes backups with Ludusavi on your Steam Deck. Syncthing is optional: it copies the *backup folder* between devices so you can use those backups on a PC or another Deck. SDH-Ludusavi does not set up Syncthing for you and does not send your saves to a remote service by itself.

Do not share a game's live save folder for this setup. Share Ludusavi's backup folder instead. Keep a backup on the Deck before you rely on another device having a copy.

## Example from this Steam Deck

- Ludusavi's backup location is `/home/deck/ludusavi-backup`.
- SyncThingy's Syncthing folder is named **ludusavi-backup**. Its folder path is the **same** `/home/deck/ludusavi-backup` folder, and its folder type is **Send & Receive**.
- The folder is shared with four other devices. You only need to share it with the devices you use.
- SyncThingy's background service is enabled, so it can run outside Desktop Mode.

This is an example, not a required folder name. If you choose a different path, use that same Deck path in both Ludusavi and Syncthing. On another device, choose a folder path that makes sense there; do not copy the Deck's `/home/deck/...` path to a PC.

## 1. Set up Ludusavi on the Deck

Install [Ludusavi](https://flathub.org/apps/com.github.mtkennerly.ludusavi) from Discover in Desktop Mode. Open it and choose where to keep backups. The example above uses `/home/deck/ludusavi-backup`. Make sure that folder exists, then use **Force Backup** for a game in SDH-Ludusavi so you have a first backup to share.

## 2. Install SyncThingy and keep it running

Install [SyncThingy](https://flathub.org/apps/com.github.zocker_160.SyncThingy) from Discover on the Deck. Open it in Desktop Mode. Its tray icon has an **Open WebUI** option for Syncthing's setup page.

For sync to continue in Gaming Mode, set up the background service once: right-click SyncThingy's tray icon, open **Settings**, select **install as system service**, copy the command it gives you, paste it into Konsole, and restart your Deck. See [SyncThingy's own background-service instructions](https://github.com/zocker-160/SyncThingy#install-background-service) if you need the full steps. The Deck used for the example has this service enabled and running.

## 3. Share the backup folder

1. Open Syncthing through SyncThingy and select **Add Folder**.
2. Give the folder a name, such as **ludusavi-backup**. Set **Folder Path** to the exact backup location shown in Ludusavi. For this Deck, it is `/home/deck/ludusavi-backup`.
3. Set **Folder Type** to **Send & Receive** and save the folder.
4. Install Syncthing on the other device. Use Syncthing's **Actions → Show ID** to find its device ID. On the Deck, choose **Add Remote Device** and add it. Accept the connection on the other device too.
5. Share **ludusavi-backup** with that device in Syncthing. Accept the shared folder on the other device and choose a suitable destination *on that device*. Keep the folder shared on both sides.

Syncthing's [Getting Started guide](https://docs.syncthing.net/intro/getting-started.html) shows how to add devices and share folders. Never paste an API key or the contents of Syncthing's configuration file into a public issue; you do not need either for these steps.

## 4. Check that it worked

With both devices connected, make a **Force Backup** in SDH-Ludusavi. Check the Syncthing page on the Deck and on the other device. Wait for the shared folder to show **Up to Date** there, then confirm that the backup is present on the other device. If you change devices later, wait for both sides to catch up *before* you use the save on the next device.

A **GAME SAVE UP TO DATE** message means the Deck's local save check or backup finished. **SYNCTHING COMPLETE** after a backup means the plugin saw at least one connected device catch up, not that every device received the backup. If a device is offline, check it after it reconnects. See [Understand your save status](save-status.md) for the other messages.

If the plugin says **PATH NOT SHARED**, check that the Syncthing folder contains the Ludusavi backup location and is shared with the intended device. If it says **NO SYNCTHING PEERS ONLINE**, check that the device is connected and sharing that folder. In either case, your local backup may still be fine; Syncthing can transfer it later when the connection is available.

Return to the [main README](../../README.md) for installation and everyday use.
