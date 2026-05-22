# SDH-Ludusavi Architectural Review Findings

**Date:** 2026-05-22  
**Subject:** Code Audit & Technical Debt Analysis

---

## 1. Frontend Architecture & Design Conventions

### A. Monolithic File Structure in [src/index.tsx](file:///home/beallio/Dropbox/Scripts/SDH-ludusavi/src/index.tsx)
* **The Issue:** At **2,621 lines of code**, [src/index.tsx](file:///home/beallio/Dropbox/Scripts/SDH-ludusavi/src/index.tsx) is a monolith. It mixes React component rendering, styling, global state variables, custom type declarations, RPC calling wrappers, DOM traversal logic, and Steam Client events. This violates the Single Responsibility Principle and degrades IDE parsing speed and maintainability.
* **Refactoring Suggestion:**
  1. Extract helper functions like `getFocusedSteamGameSession` and `getSteamUiReactPropCandidates` (which scrape elements from the GamepadUI DOM) into a utility module: `src/utils/steam.ts`.
  2. Separate individual UI modals (such as `LogModal` and `LudusaviLogModal`) into a components folder (e.g., `src/components/LogModal.tsx`).
  3. Relocate type declarations to a single declaration folder `src/types/index.ts`.

### B. Global Module State Pollution
* **The Issue:** The plugin stores active application state in loose module-scoped variables (`globalSettings`, `globalGames`, `globalGameAliases`, `globalGameHistory`, `globalInstalledAppIds`, etc.) in [src/index.tsx](file:///home/beallio/Dropbox/Scripts/SDH-ludusavi/src/index.tsx#L1438-L1444):
  ```typescript
  let globalSettings: Settings | null = null;
  let globalGames: GameStatus[] | null = null;
  let globalGameAliases: Record<string, string> | null = null;
  let globalGameHistory: Record<string, GameOperationHistory> | null = null;
  ```
  * **Why this was done:** When the Steam Deck Quick Access Menu (QAM) is opened or closed, Decky mounts and unmounts the plugin's React views. If settings were stored only in React's local component state, unmounting would delete them, triggering slow IPC rounds to the Python backend every time the QAM is opened.
  * **Why it's an anti-pattern:** Loose mutable variables bypass React's virtual DOM reconciliation, make the component hard to unit-test in isolation, create implicit state linkages, and open the door to race conditions when the backend pushes asynchronous updates.
* **Refactoring Suggestion:** Wrap the plugin state in a singleton class or context provider that is initialized once during the call to `definePlugin` and provided down via a React context hook (`useLudusaviState`). Alternatively, use a lightweight, zero-dependency state store like Zustand to isolate state outside the rendering tree in a clean, observable structure.

### C. Dynamic Style Injection & Layout Reflows
* **The Issue:** The CSS layout styles are defined as a template string `qamPanelStyles` and injected dynamically into the DOM on every render via:
  ```tsx
  return (
    <div ref={qamContentRef}>
      <style>{qamPanelStyles}</style>
      ...
    </div>
  )
  ```
  * **Why it's an anti-pattern:** Injecting `<style>` tags directly inside React component bodies forces the browser to re-evaluate and re-parse stylesheet rules on every component render, triggering unnecessary browser style recalculations and layout reflows (paint cycles).
* **Refactoring Suggestion:** Create a static stylesheet `src/index.css` and use the bundler (`rollup-plugin-postcss` or standard `@decky/rollup` pipeline configuration) to inject the CSS into the GamepadUI DOM *exactly once* when the plugin initializes.

---

## 2. Backend Concurrency & OS-Level Signaling

### A. Watchdog Safeties for Suspended Processes
* **The Issue:** The plugin implements automatic game launch synchronization by capturing the game's start hook and immediately suspending the game's process tree via `SIGSTOP` in [SDHLudusaviService.pause_game_process](file:///home/beallio/Dropbox/Scripts/SDH-ludusavi/py_modules/sdh_ludusavi/service.py#L279):
  ```python
  def pause_game_process(self, pid: int) -> dict[str, object]:
      """Suspend a launched game process tree while start sync runs."""
      pid = int(pid)
      if not _send_signal_tree(pid, signal.SIGSTOP):
          ...
  ```
  It then attempts a backup or conflict resolution check, resuming the process tree via `SIGCONT` after completion.
  * **The Risk:** If the Decky Loader Python process crashes, the plugin unloads abnormally, or an unhandled exception triggers in a concurrent thread before the exit hook is invoked, the game's process tree remains permanently suspended (`SIGSTOP`). The user's game will freeze and become unresponsive.
* **Refactoring Suggestion:** Register a separate background cleanup timer or daemon thread that regularly verifies if any PID in `self._paused_pids` has been suspended for longer than a maximum timeout (e.g., 15 seconds) and automatically resumes them if the service is stuck.

### B. Synchronous Threading Wrapper Simplification
* **The Issue:** In [main.py](file:///home/beallio/Dropbox/Scripts/SDH-ludusavi/main.py#L294), the async-to-sync executor [_run_blocking](file:///home/beallio/Dropbox/Scripts/SDH-ludusavi/main.py#L294) manages a custom `asyncio.Future` and instantiates a raw daemon thread (`threading.Thread`) for every blocking call.
* **Refactoring Suggestion:** Since the plugin requires Python 3.12, delegate blocking calls using standard async-to-thread executors or `asyncio.to_thread` instead of manually managing low-level thread allocations.
