# SDH-Ludusavi

SDH-Ludusavi keeps your game saves protected without pulling you out of Game Mode. It brings Ludusavi's backup and restore tools into Decky Loader, checks for newer saves before launch, and backs up your progress when you quit.

![SDH-Ludusavi demo](assets/demo.webp?cacheBuster=2)

## Features

- **Automatic Sync**: Restores your save if the backup is newer before a game starts, and automatically performs a backup after you exit. Each Ludusavi-managed game also has a **Sync This Game** toggle that defaults to on. Turning it off blocks both the launch restore and exit backup for that game; the preference remains editable but has no effect while global Automatic Sync is off. With global sync on, starting or exiting a disabled game briefly shows **SAVE SYNC DISABLED FOR THIS GAME**.
- **SteamOS Integration**: Shows compact progress strips for background sync events, just like official Steam Cloud sync.
- **Syncthing Activity**: Shows Syncthing sync status (downloading, uploading, or complete) on the autosync status strip when Syncthing is configured and running.
- **Launch Gate**: Pauses game launch for save conflicts and observed incoming Syncthing activity, verifying stable backup files before deciding which save to use.
- **Manual Control**: Force a backup for any Ludusavi-managed game at any time, and restore from any snapshot through the Backup Browser.
- **Backup Browser**: View historical backup snapshots for a game directly in the plugin and selectively perform a point-in-time restore.
- **Unified Logging**: View backend and frontend logs directly within the plugin's "View Logs" modal. Optionally enable **Debug Logging** for verbose diagnostics.
- **In-Plugin Updates**: Automatically or manually check for newer GitHub Release builds, choose between Stable and Development channels, and perform one-click installations via Decky Loader.

## Installation (Early Access)

As the plugin is currently in development and not yet available in the Decky Store, follow these steps to install it manually.

Download the latest release archive from the [GitHub Releases](https://github.com/beallio/SDH-Ludusavi/releases) page. Always download the versioned ZIP file (e.g., `SDH-Ludusavi-vX.Y.Z.zip`).

> [!WARNING]
> Prereleases (versioned with `-dev.gSHORTSHA`) are intended for development, testing, and early access. They may contain bugs and should be used with caution.

### 1. Enable Decky Loader Developer Mode
1. Open the Decky Loader menu in the Steam Deck Quick Access Menu (QAM).
2. Go to **Settings** (the gear icon).
3. Under **General**, scroll down to find **Developer Mode** and toggle it **On**.

### 2. Install the Plugin
You have two options for manual installation through the Decky Loader's Developer menu:

- **Option A: Install from URL**
  1. In the Decky Settings, go to the **Developer** tab.
  2. Select **Install from URL**.
  3. Enter the URL for the desired SDH-Ludusavi release ZIP from GitHub Releases (for example, `https://github.com/beallio/SDH-Ludusavi/releases/download/vX.Y.Z/SDH-Ludusavi-vX.Y.Z.zip`) and click **Install** after replacing `X.Y.Z` with the release version.

- **Option B: Install from Local ZIP**
  1. Download the latest versioned `SDH-Ludusavi-vX.Y.Z.zip` to your Steam Deck.
  2. In the Decky Settings, go to the **Developer** tab.
  3. Select **Install from Local ZIP**.
  4. Navigate to and select the downloaded `.zip` file.

## In-Plugin Updates

Once installed, the plugin can handle updates directly from the UI:

- **Update Channels**: Choose between **Stable releases only** (default) or **Development releases** (includes prereleases for testing).
- **Automatic & Manual Checks**: Optionally check for updates in the background or trigger a manual check at any time.
- **Security Validation**: Pre-validates release checksums and metadata before initiating Decky's native installation prompts.
- **Manual Fallback & Recovery**: If one-click installation fails (e.g., due to a temporary network issue or Decky API drift), you can view release notes on GitHub and perform a manual reinstall using Option A or B.

## Prerequisites

- **[Decky Loader](https://github.com/SteamDeckHomebrew/decky-loader)**: Installed and running on your Steam Deck.
- **[Ludusavi Flatpak](https://flathub.org/apps/com.github.mtkennerly.ludusavi)**: This plugin requires the Ludusavi Flatpak to manage saves. You can install it from the Discover store or via terminal:
  ```bash
  flatpak install flathub com.github.mtkennerly.ludusavi
  ```

## Recommended Workflow (The "Gold Standard")

For the best experience, we recommend pairing SDH-Ludusavi with **[SyncThingy](https://flathub.org/apps/com.github.zocker_160.SyncThingy)** to ensure your saves are synchronized across devices without the lag or offline limitations of traditional cloud providers.

### 1. Setup SyncThingy
1. Install the SyncThingy Flatpak:
   ```bash
   flatpak install flathub com.github.zocker_160.SyncThingy
   ```
2. Open SyncThingy and follow its internal instructions to set up the systemd service for background synchronization.
3. (Optional) Install the **Syncthing** plugin from the Decky Store to monitor sync status directly from Game Mode.

### 2. Configure Save Sync
1. In **Ludusavi**, set your backup directory to a folder that SyncThingy will watch (e.g., `/home/deck/ludusavi-backup`).
2. In **SyncThingy**, share that folder with your other nodes (PC, other Deck, etc.).
3. **Note**: Ensure that at least one node is online during sync events (game start/exit) to guarantee your saves propagate correctly.

### 3. Why Syncthing?
While Ludusavi supports traditional cloud providers (rclone), using them can introduce significant lag during game launch and exit as files are uploaded/downloaded. Furthermore, cloud sync will fail if your Steam Deck is offline.

Using Syncthing allows for near-instant local backups that sync in the background. You can still use Ludusavi's [Backup Retention](https://github.com/mtkennerly/ludusavi/blob/master/docs/help/backup-retention.md) settings to manage versions and diffs.

*See also: Ludusavi [Cloud Backup](https://github.com/mtkennerly/ludusavi/blob/master/docs/help/cloud-backup.md) documentation.*

## Understanding Status Messages

Backups and restores are limited to 15 minutes (status checks to 5 minutes); if Ludusavi exceeds this — for example, a stalled cloud sync — the operation is reported as failed instead of hanging, and any paused game is resumed automatically.

- **Backup ready**: Ludusavi has a valid backup for this game.
- **Needs first backup**: Ludusavi recognizes the game, but no backup has been created yet.
- **Skipped — local save is already current**: The plugin detected that your local save matches or is newer than the backup, so no restore was performed.
- **Skipped — recency is ambiguous**: The plugin couldn't determine which save is newer and will prompt you to choose. This also occurs when your local save and the backup have both changed (for example, after playing in Desktop Mode); the plugin only restores automatically when the backup is clearly newer, and otherwise pauses the launch so you can choose.
- **Sync Skipped — Conflict Unresolved**: You dismissed the conflict prompt without choosing a save, so the plugin deliberately made no save changes and resumed the game.
- **Syncthing Downloading**: Syncthing is downloading/applying backup folder data.
- **Syncthing Uploading**: Syncthing is uploading/serving backup folder data to a remote peer.
- **Syncthing Complete**: Syncthing synchronization has settled locally. This confirms there is no longer active transfer or scanning on the Steam Deck, but it does NOT guarantee that remote devices have finished downloading the save.
- **Local Backup Saved - Syncthing Unavailable**: The backup succeeded, but configured Syncthing API access failed.
- **Local Backup Saved - Path Not Shared**: The backup succeeded, but its directory is not in a Syncthing shared folder, or the shared folder has no configured remote devices.
- **Local Backup Saved - No Syncthing Peers Online**: The backup succeeded, but none of the devices that share the backup folder are currently connected, so remote propagation was not observed. Syncthing will sync later once a peer reconnects.

When Syncthing is not configured, the plugin silently reports the normal local-backup result without a Syncthing warning. Peer connectivity, not internet connectivity, controls these warnings: Syncthing monitoring runs whenever at least one device sharing the backup folder is connected (including over LAN without internet), and is skipped when none are.

Syncthing activity statuses reflect only the Syncthing folder that contains Ludusavi's configured backup path. Traffic in other Syncthing folders is excluded, even when those folders are shared with the same remote peer.

If incoming activity is already visible during a launch check, the game remains paused
until that folder settles. The plugin then verifies the save again and uses only the
fresh result; it does not restore from a preview captured while Syncthing was changing
the backup folder.

## License

Project-authored code is available under the MIT License. Retained portions from decky-ludusavi and the Decky plugin template remain under BSD-3-Clause, and bundled third-party components retain their own licenses. See [LICENSE](LICENSE) and [NOTICE.md](NOTICE.md) for project lineage, design inspiration, and third-party attribution. For technical documentation, see [DEVELOPMENT.md](DEVELOPMENT.md).
