# SDH-Ludusavi

SDH-Ludusavi keeps your game saves protected without pulling you out of Game Mode. It brings Ludusavi's backup and restore tools into Decky Loader, checks for newer saves before launch, and backs up your progress when you quit.

![SDH-Ludusavi demo](assets/demo.webp?cacheBuster=11)

![Ludusavi showing Up to date on a non-Steam game details page](assets/native-status-row.webp?cacheBuster=11)

The read-only Ludusavi row keeps the latest save result visible without opening the Decky menu.

## Features

- **Automatic Sync**: Restores your save if the backup is newer before a game starts, and automatically performs a backup after you exit. Each Ludusavi-managed game also has a **Sync This Game** toggle that defaults to on. Turning it off blocks both the launch restore and exit backup for that game; the preference remains editable but has no effect while global Automatic Sync is off. With global sync on, starting or exiting a disabled game briefly shows **SAVE SYNC DISABLED FOR THIS GAME**.
- **SteamOS Integration**: Shows one read-only Ludusavi save-status row in the native status band on eligible non-Steam game details pages. Steam Cloud-enabled entries keep their native Steam Cloud row unchanged; this display rule does not change backup or restore eligibility. The row identifies local results separately from observed remote Syncthing results. A separate compact strip remains on the launch screen for protected checking, restore, and conflict work.
- **Syncthing Activity**: Shows observed Syncthing activity and outcomes. A successful local backup is not presented as proof that a remote device received it.
- **Launch Gate**: Pauses game launch for save conflicts and observed incoming Syncthing activity, verifying stable backup files before deciding which save to use.
- **Manual Control**: Force a backup for any Ludusavi-managed game at any time, and restore from any snapshot through the Backup Browser.
- **Backup Browser**: View historical backup snapshots for a game directly in the plugin and selectively perform a point-in-time restore.
- **Unified Logging**: View backend and frontend logs directly within the plugin's "View Logs" modal. Optionally enable **Debug Logging** for verbose diagnostics.
- **In-Plugin Updates**: Automatically or manually check for newer GitHub Release builds, choose between Stable and Development channels, and perform one-click installations via Decky Loader.

## Installation (Early Access)

As the plugin is currently in development and not yet available in the Decky Store, install it using one of the two methods below.

> [!WARNING]
> Prereleases (versioned with `-dev.gSHORTSHA`) are intended for development, testing, and early access. They may contain bugs and should be used with caution.

### Method 1: Guided Desktop Installer (Recommended)

Download **[SDH-Ludusavi Installer Bundle.zip](https://github.com/beallio/SDH-Ludusavi/raw/main/SDH-Ludusavi%20Installer%20Bundle.zip)** from this repository.

Use this for **both a first-time install and for updating** an existing install. The installer finds the newest release on GitHub, verifies its SHA-256 checksum before installing, and replaces any existing copy in place — rolling back automatically if anything fails. Decky Loader Developer Mode is **not** required.

1. Switch the Steam Deck to **Desktop Mode**.
2. Extract the archive onto the Desktop, so that the `DeckyPluginInstaller` folder and `Install SDH-Ludusavi Decky Plugin` sit directly on the Desktop.
3. Double-click **Install SDH-Ludusavi Decky Plugin**.
4. Approve the installation and administrator-authentication prompts.
5. Return to Gaming Mode. If the plugin does not appear immediately, restart Steam.

No Konsole window is needed. The installer writes a log to `/home/deck/Desktop/Decky Plugin Installer.log`.

To update later, run the same installer again — it always fetches the latest release. You can also update from inside the plugin itself; see [In-Plugin Updates](#in-plugin-updates).

> [!NOTE]
> If the launcher does nothing when double-clicked, KDE may not trust it yet. Right-click it, choose **Properties → Permissions**, and ensure it is executable — or right-click and select **Run**.

### Method 2: Manual install via Decky Loader

Download the latest release archive from the [GitHub Releases](https://github.com/beallio/SDH-Ludusavi/releases) page. Always download the versioned ZIP file (e.g., `SDH-Ludusavi-vX.Y.Z.zip`).

#### 1. Enable Decky Loader Developer Mode
1. Open the Decky Loader menu in the Steam Deck Quick Access Menu (QAM).
2. Go to **Settings** (the gear icon).
3. Under **General**, scroll down to find **Developer Mode** and toggle it **On**.

#### 2. Install the Plugin
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
- **Automatic & Manual Checks**: When automatic checks are enabled, the plugin checks in the background 30 seconds after loading and every 6 hours afterward, even while the QAM panel is closed. You can also trigger a manual check at any time.
- **Update Notifications**: A newly available release raises one toast per release tag. The **Plugin Updates** notification toggle controls these toasts, and the master **All Notifications** toggle silences them with every other plugin notification.
- **Security Validation**: Pre-validates release checksums and metadata before initiating Decky's native installation prompts.
- **Manual Fallback & Recovery**: If one-click installation fails (e.g., due to a temporary network issue or Decky API drift), you can view release notes on GitHub and reinstall using the [guided desktop installer](#method-1-guided-desktop-installer-recommended) or either manual option.

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

The Game Details row gives you a quick save status:

- **Checking, Backing up, Restoring, Uploading, or Downloading**: Save work is in progress.
- **Up to date**: The latest save check finished successfully.
- **Out of sync**: This game needs its first backup.
- **File conflict**: Choose which save to keep.
- **Unable to sync**: The last save or remote sync check did not finish.
- **Disabled**: Automatic sync is off for this game.
- **Unknown**: No clear recent result is available.

Local backups and remote sync are reported separately. **Up to date** does not mean that an
offline device has received the save. If save work stalls or overlaps another task, the plugin
stops safely and reports the problem instead of guessing.

## License

Project-authored code is available under the MIT License. Retained portions from decky-ludusavi and the Decky plugin template remain under BSD-3-Clause, and bundled third-party components retain their own licenses. See [LICENSE](LICENSE) and [NOTICE.md](NOTICE.md) for project lineage, design inspiration, and third-party attribution. For technical documentation, see [DEVELOPMENT.md](DEVELOPMENT.md).
