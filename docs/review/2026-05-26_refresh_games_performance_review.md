# Ludusavi Binary Call Optimization Review

## Original Review Finding

> **Reviewer Comment / Rationale:**
> "refresh_games triggers multiple expensive Ludusavi binary calls (backup --preview, backups list, and config show) via the adapter. This causes significant UI latency, especially for users with large libraries. The plugin should explore ways to batch these calls or cache get_aliases more aggressively, as aliases change infrequently."

### Location
- **File(s):** `py_modules/sdh_ludusavi/service.py`, `py_modules/sdh_ludusavi/ludusavi.py`
- **Function/Class/Lines:** `SDHLudusaviService.refresh_games`, `PyludusaviAdapter.refresh_statuses`, `PyludusaviAdapter.get_aliases`

### Requested Change
- Implement aggressive caching for game aliases in `PyludusaviAdapter`.
- Investigate if `refresh_statuses` can be optimized or if partial refreshes are possible.
- Ensure that `refresh_games` only performs the absolute minimum set of binary calls needed to satisfy the `force` flag.

### Acceptance Criteria
- [ ] The number of Ludusavi binary calls per `refresh_games` (when not forced) is reduced.
- [ ] Aliases are cached and invalidated only when the Ludusavi config mtime changes.
- [ ] Unit tests verify that data remains consistent after optimization.

---

## Research & Analysis

1. **Subprocess Spawn Latency:**
   Every subprocess spawn of the Ludusavi binary (especially under Flatpak on Steam Deck) takes roughly **200–500ms**. Spawning 3 sequential subprocesses (`backup --preview`, `backups list`, `config show`) blocks the service and the UI for **600ms to 1.2s**.

2. **Custom Game Aliases (`get_aliases`):**
   - **File:** `py_modules/sdh_ludusavi/ludusavi.py`
   - Custom game aliases change *only* when the Ludusavi configuration file changes.
   - We can check if the file has changed by querying `get_config_mtime_ns()`, which executes a direct python `stat()` call on the config file. Since `stat()` is a direct filesystem syscall, it has **zero process-spawning overhead** (< 1ms).
   - caching the alias list and returning it directly when the config `mtime` hasn't changed will completely eliminate the `config show` subprocess call in most cases.

3. **Status Queries (`refresh_statuses`):**
   - **File:** `py_modules/sdh_ludusavi/ludusavi.py`
   - Spawns `backup --preview` and `backups list`. Both are read-only operations that do not mutate state.
   - By running them concurrently using standard library threads (`concurrent.futures.ThreadPoolExecutor`), we can cut the status refresh time in half, reducing latency to $\max(t_{\text{preview}}, t_{\text{backups}})$.

---

## Proposed Solution

### 1. `PyludusaviAdapter` Aliases Cache
Initialize cache variables and check configuration `mtime` in `get_aliases()` before spawning `config show`:

```python
class PyludusaviAdapter:
    def __init__(self, flatpak_id: str = FLATPAK_ID) -> None:
        # ...
        self._cached_aliases: dict[str, str] | None = None
        self._cached_aliases_mtime_ns: int | None = None

    def get_aliases(self) -> dict[str, str]:
        try:
            current_mtime = self.get_config_mtime_ns()
        except Exception as exc:
            LOGGER.debug("Failed to get config mtime for aliases caching: %s", exc)
            current_mtime = None

        if (
            getattr(self, "_cached_aliases", None) is not None
            and getattr(self, "_cached_aliases_mtime_ns", None) == current_mtime
            and current_mtime is not None
        ):
            return dict(self._cached_aliases)

        aliases: dict[str, str] = {}
        try:
            config = self._client.config_show().data
            for game in config.get("customGames", []):
                name = game.get("name")
                alias = game.get("alias")
                if name and alias:
                    aliases[name] = alias
            self._cached_aliases = dict(aliases)
            self._cached_aliases_mtime_ns = current_mtime
        except (LudusaviError, KeyError, TypeError, ValueError, AttributeError) as exc:
            LOGGER.debug("Failed to retrieve custom game aliases: %s", exc)
            if getattr(self, "_cached_aliases", None) is not None:
                return dict(self._cached_aliases)
        return aliases
```

### 2. Parallel Status Retrieval in `PyludusaviAdapter`
Run `backup(preview=True)` and `backups_list()` concurrently:

```python
    def refresh_statuses(self) -> list[dict[str, object]]:
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            future_preview = executor.submit(self._client.backup, preview=True)
            future_backups = executor.submit(self._client.backups_list)
            preview = future_preview.result().data
            backups = future_backups.result().data

        preview_games = _games_from_output(preview)
        backup_games = _games_from_output(backups)
        # ...
```
