# SDH-Ludusavi

SDH-Ludusavi helps you back up and restore game saves from Gaming Mode on your Steam Deck. It uses Ludusavi to keep copies of your saves. If you turn on **Automatic Sync**, it checks for a newer backup before a game starts and backs up your saves when you quit.

![SDH-Ludusavi in Gaming Mode](assets/demo.webp?cacheBuster=14)

You can see the latest save result on supported non-Steam game pages without opening the Decky menu. After automatic work when you quit a game, that game's page shows the full save message, such as local backup, upload, or upload-warning progress. If you leave the page, the post-game message hides but the work continues. Returning shows the latest active state or retained result. Steam Cloud pages keep their usual Steam Cloud status.

![Ludusavi showing Up to date on a non-Steam game page](assets/native-status-row.webp?cacheBuster=14)

## Before you install

- Install [Decky Loader](https://github.com/SteamDeckHomebrew/decky-loader) on your Steam Deck.
- Install [Ludusavi](https://flathub.org/apps/com.github.mtkennerly.ludusavi) from the Discover app in Desktop Mode. SDH-Ludusavi needs Ludusavi to make backups.

## Install SDH-Ludusavi

SDH-Ludusavi is not in the standard Decky Store. Choose one of these ways to install it.

### Option 1: Decky Plugins Extended (in Gaming Mode)

[Decky Plugins Extended](https://github.com/beallio/decky-plugins-extended) is a custom Decky store that includes SDH-Ludusavi. You do not need Developer Mode for this option.

1. Open the **Quick Access Menu**, select the **Decky Loader** plug icon, then open **Settings** (the gear icon).
2. On the **General** tab, set **Store Channel** to **Custom**.
3. Set **Custom Store** to:

   ```text
   https://decky-extended-plugins.beallio.com/plugins.json
   ```

4. Return to the Decky Store (the shopping bag icon), find **SDH-Ludusavi**, and select **Install**.

This changes the store list you see in Decky. You can switch **Store Channel** back to your previous setting later; the plugin you installed stays on your Deck.

### Option 2: Desktop installer

Download the [SDH-Ludusavi Installer Bundle.zip](https://github.com/beallio/SDH-Ludusavi/raw/main/SDH-Ludusavi%20Installer%20Bundle.zip). Use it for a first install or to update an existing copy. You do not need Developer Mode.

1. Switch your Steam Deck to **Desktop Mode**.
2. Extract the ZIP onto the Desktop. The `DeckyPluginInstaller` folder and **Install SDH-Ludusavi Decky Plugin** launcher should both be on the Desktop.
3. Double-click **Install SDH-Ludusavi Decky Plugin** and approve the prompts, including the request for your administrator password.
4. Return to Gaming Mode. If the plugin does not appear, restart Steam.

If double-clicking the launcher does nothing, right-click it and choose **Run**. If needed, open **Properties → Permissions** and allow it to run. The installer writes a log named **Decky Plugin Installer.log** on your Desktop if you need help.

### Option 3: Install a release ZIP through Decky

1. Download the latest stable **SDH-Ludusavi-v…zip** file from [GitHub Releases](https://github.com/beallio/SDH-Ludusavi/releases). Do not download the installer bundle for this option.
2. In Decky Loader **Settings → General**, turn on **Developer Mode**.
3. Open the **Developer** tab and choose **Install from Local ZIP**.
4. Select the release ZIP you downloaded and follow Decky's prompts.

## Start using it

1. Open Ludusavi in Desktop Mode and choose a folder for your backups.
2. In Gaming Mode, open **SDH-Ludusavi** from the Decky menu. Select a game and choose **Force Backup** to make its first backup.
3. Turn on **Automatic Sync** to check for newer backups before games start and back up saves when you quit. **Sync This Game** lets you turn this off for one game without changing the others.

You can still use **Force Backup** and **Browse Backups** when Automatic Sync is off. Browse Backups lets you choose an older copy to restore. Check the date before restoring: restoring an older copy can replace your current save.

If a game is missing from the list, check that Ludusavi recognizes it, then choose **Refresh Games** in the plugin. Automatic Sync cannot restore a game until a backup exists.

## Understand the save status

The game page can show **Checking**, **Backing up**, **Restoring**, **Up to date**, **Out of sync**, or an error. **Out of sync** can mean a game needs its first backup. If the plugin finds a save conflict, it asks which copy you want to keep before the game starts. During this check, a separate message can appear on the game launch screen.

A completed local backup is not proof that another device has received it. If you also use Syncthing, the plugin shows the remote activity it can observe separately from local backup results. An offline device may still need to catch up. [Read the save-status guide](docs/guides/save-status.md) for more about each message.

## Sync backups with another device (optional)

You do not need another app to keep backups on your Steam Deck. To share them with a PC or another Deck, you can install [SyncThingy](https://flathub.org/apps/com.github.zocker_160.SyncThingy) from Discover and follow its setup instructions. Point Ludusavi at a backup folder that SyncThingy shares with your other device.

Syncthing sends the backups in the background when the devices can connect. Check its status on your other device before you rely on a backup there. The optional Syncthing plugin for Decky can also show connection status in Gaming Mode. [Follow the Syncthing setup guide](docs/guides/syncthing.md) for an example from a Steam Deck.

## Change the look of the status bars (optional)

The Ludusavi bar uses Steam's game-page styles. A theme that changes the Steam Cloud bar can also change the Ludusavi bar's text, size, position, or visibility. If a theme hides, covers, clips, or cannot fit the full post-game message, that game's page can use the separate status strip. Home and other game pages stay quiet for that work. Protected game-launch messages always use that strip.

If you use [CSS Loader](https://docs.deckthemes.com/CSSLoader/), SDH-Ludusavi adds an **SDH-Ludusavi Status** theme. In CSS Loader, use **Save Status** to choose:

- **Default:** Keep the usual Steam Cloud and Ludusavi bars.
- **Clean View:** Give both bars a plain dark background.
- **Custom:** Choose the background, text, icon, and outline colors. You can also make the bars partly transparent.

The theme changes how the bars look on game pages, not how saves work. Warning and error bars keep their distinct appearance. The separate message on the game launch screen does not change. When you install or update SDH-Ludusavi, it asks CSS Loader to reload the theme if its files changed. If the theme is missing or the new look does not appear, choose **Refresh** in CSS Loader. Your choices stay in place when you update SDH-Ludusavi.

On game pages without a save-status bar, the theme leaves a blank row below the play controls before Activity. Clean View and Custom give this space the same background as their status bars; Custom also uses your outline choice. If you use Clean Gameview, the game's picture or trailer can show through the blank row. It does not show a save result. On an uninstalled Steam game, you may need to scroll down to see Activity.

With Clean Gameview, the picture follows the visible, full-width status bar's height. A compact, moved, or hidden bar does not add full-width picture space. Opening a game page or switching from its picture to a trailer does not add a second size change. Steam's normal page animation still plays.

## Updates and help

Open **Updates** in SDH-Ludusavi to check for a new release or enable automatic checks. The plugin offers stable releases by default. **Receive development releases** is optional; those builds are for testing and may have bugs. When an update is available, Decky asks you to confirm the installation.

If an update from the plugin does not work, use the [desktop installer](#option-2-desktop-installer) or a [release ZIP](#option-3-install-a-release-zip-through-decky). Open **View Logs** in the plugin if you need to report a problem on the [issue page](https://github.com/beallio/SDH-Ludusavi/issues).

## License

Project code is available under the MIT License. Some code from decky-ludusavi and the Decky plugin template uses the BSD-3-Clause license, and bundled components keep their own licenses. See [LICENSE](LICENSE) and [NOTICE.md](NOTICE.md) for details. Developer information is in [DEVELOPMENT.md](DEVELOPMENT.md).
