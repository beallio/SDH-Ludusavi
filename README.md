# SDH-ludusavi

SDH-ludusavi is a Decky Loader plugin that surfaces Ludusavi save backup and
restore controls in the Steam Deck side panel.

Ludusavi remains the source of truth for configured games, backup paths, cloud
settings, and restore behavior. The plugin stores only local UI state, cached
game status, operation status, and recent operation logs.

## Features

- Automatic Sync toggle for conservative start/exit sync behavior.
- Ludusavi game selector using Ludusavi game names as canonical IDs.
- Refresh Games, Force Backup, and Force Restore actions.
- Manual backup and restore remain available when Automatic Sync is disabled.
- Ludusavi and rclone version display through the Ludusavi Flatpak environment.
- Missing Flatpak, missing rclone, missing config, and command failures appear in
  the panel and logs.

## Requirements

- Decky Loader.
- Ludusavi Flatpak: `com.github.mtkennerly.ludusavi`.
- Python package dependency: `pyludusavi`.
- Frontend dependencies from `package.json`.

## Development Setup

Use the wrapper so Python virtual environments and caches stay outside Dropbox:

```bash
./run.sh uv sync
```

The wrapper stores Python tooling state under `/tmp/sdh_ludusavi`.

Install frontend dependencies when needed:

```bash
pnpm install
```

## Usage

Run backend tests:

```bash
./run.sh uv run pytest
```

Build the Decky frontend:

```bash
pnpm run build
```

## Validation

Before committing changes, run:

```bash
./run.sh uv run ruff check . --fix
./run.sh uv run ruff format .
./run.sh uv run ty check src/
./run.sh uv run pytest
pnpm run build
```

## License

MIT - See [LICENSE](LICENSE) for details.
