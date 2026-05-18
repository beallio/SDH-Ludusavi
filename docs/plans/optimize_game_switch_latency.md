# Plan: Optimize UI Responsiveness and "Warmed Boot" State Management

## Overview
This plan details the technical steps to achieve near-instantaneous UI responses when switching games and to eliminate the "Loading game list..." flicker when the plugin panel is re-opened.

## 1. Backend: Asynchronous Settings Persistence
Currently, updating plugin settings (like selecting a game) blocks the main Decky thread while performing file I/O. We will offload these operations to background threads.

### Implementation Detail (`main.py`)
Wrap the following RPC methods in `_call` (which utilizes `_run_blocking`):
- `set_selected_game`
- `set_auto_sync_enabled`

```python
# Proposed change in main.py
async def set_selected_game(self, game_name: str) -> dict[str, Any]:
    return await self._call(
        "set_selected_game", 
        lambda: self._service().set_selected_game(game_name)
    )
```

## 2. Backend: Subprocess Optimization (Adapter Caching)
The `PyludusaviAdapter` currently calls `ludusavi config path` frequently to check for configuration changes. Since this path is static for a given installation, we will cache it in memory.

### Implementation Detail (`py_modules/sdh_ludusavi/ludusavi.py`)
- Add a private `_cached_config_path` variable to the `PyludusaviAdapter` class.
- Update `get_config_mtime_ns` to populate and use this cache.

```python
# Proposed change in PyludusaviAdapter
def get_config_mtime_ns(self) -> int | None:
    if self._cached_config_path is None:
        try:
            self._cached_config_path = self._client.config_path()
        except Exception:
            return None
    try:
        return Path(self._cached_config_path).stat().st_mtime_ns
    except Exception:
        return None
```

## 3. Frontend: "Warmed Boot" Architecture
To prevent the UI from resetting every time the Decky panel is closed and re-opened, we will move the core state (Settings, Games, History) to module-level variables.

### Architecture Diagram (Text-based)
```text
[ First Mount ] -> [ No Global Cache ] -> [ Set "Loading" ] -> [ Fetch Data ] -> [ Populate Cache ] -> [ Render UI ]
[ Second Mount] -> [ Global Cache Exists ] -> [ Render UI Instantly ] -> [ Fetch Data (Silent) ] -> [ Update UI ]
```

### Implementation Detail (`src/index.tsx`)
1. **Global Store**: Define globals for `settings`, `games`, `gameHistory`, and `versions` outside the `Content` component.
2. **Instant Init**: Initialize the component's `useState` hooks from these globals.
3. **Optimized `loadInitial`**: 
   - Check if `globalGames` has data.
   - If yes: skip `setBusyLabel("Loading")` but still trigger the background fetch.
   - If no: show "Loading" as usual.

```typescript
// Proposed global state in src/index.tsx
let globalSettings: Settings | null = null;
let globalGames: GameStatus[] | null = null;
let globalHistory: Record<string, GameOperationHistory> | null = null;

function Content() {
  const [settings, setSettings] = useState<Settings>(globalSettings ?? { auto_sync_enabled: false, selected_game: "" });
  const [games, setGames] = useState<GameStatus[]>(globalGames ?? []);
  // ...
  
  const loadInitial = async () => {
    const isWarmed = !!globalGames;
    if (!isWarmed) {
        setBusyLabel("Loading");
    }
    try {
        // ... fetch data ...
        // apply results
    } finally {
        setBusyLabel(null);
    }
  }
}
```

## Verification
1. **Log Analysis**: Verify that `set_selected_game` shows "sdh-ludusavi-worker" in the thread name.
2. **Process Monitoring**: Verify (via `top` or logs) that only one Ludusavi process is spawned during the "fast refresh" check (version and path discovery are avoided or cached).
3. **Visual UI Check**: Switch a game; the status line should update without any "Loading" text appearing. Re-opening the panel should show the previous game list instantly.
