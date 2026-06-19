---
name: Code Review Action Item
about: Address feedback from a code review or tackle technical debt
title: 'refactor: Prevent late settings responses from overwriting newer fields'
labels: 'tech-debt, code-review'
assignees: ''
---

## 🔍 The Review Finding
**Reviewer Comment / Rationale:**
> "The settings queue treats each setting as independently versioned, but every RPC returns and reapplies the entire Settings object. After a request times out, the queue starts the next mutation while the original request remains live. A late response is accepted when its own per-setting sequence is current, even if it contains stale values for other settings. An isolated test against dev reproduced a timed-out auto-sync response overwriting a newer notification change. This is a correctness defect caused by incompatible concurrency and response-granularity models."

## 📍 Exact Location
- **Original PR (if applicable):** #
- **File(s):** `src/settings/settingsMutationRuntime.ts`, `src/settings/settingsMutationRuntime.test.ts`, `src/state/ludusaviState.tsx`
- **Function/Class/Lines:** `createSettingsMutationRuntime()` lines 35-442; `mutateSetting()` lines 158-254; setting call sites lines 256-401; `LudusaviStateStore.applySettings()` lines 127-136

## 🛠️ Requested Change
- Replace per-setting acceptance of whole-settings responses with one coherent strategy: either merge only the field owned by the completed mutation, or attach a global mutation revision and reject any full snapshot older than any subsequently queued mutation.
- Keep optimistic updates and timeout recovery, but ensure a timed-out request cannot later mutate unrelated fields.
- Remove the `any` fields from `MutateOptions` and type persisted values against the setting being changed.

## ✅ Acceptance Criteria
- [ ] The code implements the requested change.
- [ ] Existing unit tests still pass (no regressions).
- [ ] Add a regression test where one setting times out, a different setting succeeds, and the first request resolves late without reverting the second setting.
- [ ] Add equivalent coverage for late failures and for at least one non-boolean setting.

## 🚫 AI Constraints & Scope Limits
- Do not refactor code outside of the specified function/file.
- Do not change the public API or return types of the affected functions.
- Do not add new third-party libraries.

---
name: Code Review Action Item
about: Address feedback from a code review or tackle technical debt
title: 'refactor: Make the plugin update workflow an explicit tested state machine'
labels: 'tech-debt, code-review'
assignees: ''
---

## 🔍 The Review Finding
**Reviewer Comment / Rationale:**
> "The update workflow is an implicit state machine spread across eight React state values, seven refs, three effects, timeout IDs, and a detached async closure. The RPC boundary also lies about failure results: `_call()` resolves backend exceptions as `{status: 'failed'}`, while update context calls are typed as unconditional `UpdateCheckContext`. `install()` ignores the result of `recordUpdateInstallRequestedCall()` and can invoke the installer after persistence failed. There is no dedicated frontend test suite for this 508-line controller."

## 📍 Exact Location
- **Original PR (if applicable):** #
- **File(s):** `src/controllers/pluginUpdateController.tsx`, `src/api/ludusaviRpc.ts`, `src/types/index.ts`, `main.py`
- **Function/Class/Lines:** `usePluginUpdateController()` lines 70-508; update state/refs lines 76-94; hydration/check effects lines 274-380; `install()` lines 382-494; RPC declarations lines 85-90; `Plugin._call()` lines 420-445

## 🛠️ Requested Change
- Move update check/install/handoff transitions into a framework-independent reducer or controller with a discriminated state such as `hydrating`, `idle`, `checking`, `available`, `recording`, `handoff_pending`, `installed`, and `failed`.
- Correct the frontend RPC annotations to acknowledge resolved `RpcStatus` failures, and reject a failed pending-install record before invoking Decky Installer.
- Keep React responsible only for binding props/effects and rendering controller state.

## ✅ Acceptance Criteria
- [ ] The code implements the requested change.
- [ ] Existing unit tests still pass (no regressions).
- [ ] Add controller tests for failed pending-install persistence, timed-out checks, stale checks, slow installer handoff, rejected handoff, hydration with a pending install, and unmount cleanup.
- [ ] Decky Installer is never invoked unless revalidation and pending-install persistence both succeed.

## 🚫 AI Constraints & Scope Limits
- Do not refactor code outside of the specified function/file.
- Do not change the public API or return types of the affected functions.
- Do not add new third-party libraries.

---
name: Code Review Action Item
about: Address feedback from a code review or tackle technical debt
title: 'refactor: Remove continuous hidden-QAM Steam UI polling'
labels: 'tech-debt, code-review'
assignees: ''
---

## 🔍 The Review Finding
**Reviewer Comment / Rationale:**
> "While Quick Access is hidden—the normal steady state—the component runs `captureSteamUiGameContext()` every 500 ms. Each capture can query route state, call `querySelectorAll(':hover')`, inspect focused DOM nodes, enumerate private React properties, and walk React Fiber parents. This is a persistent UI-thread tax on Steam Deck hardware for data with a 10-second TTL. The implementation should react to navigation/focus changes, not continuously scrape React internals at 2 Hz."

## 📍 Exact Location
- **Original PR (if applicable):** #
- **File(s):** `src/components/qam/LudusaviContent.tsx`, `src/utils/steam.ts`, `src/utils/steam.test.ts`
- **Function/Class/Lines:** hidden-QAM effect lines 243-251; `getSteamUiReactPropCandidates()` lines 191-228; `getSteamUiFocusedElements()` lines 230-251; `getFocusedSteamGameSession()` lines 253-277; `captureSteamUiGameContext()` lines 279-298

## 🛠️ Requested Change
- Replace the unconditional 500 ms interval with event-driven capture from route/navigation and focus changes.
- If a polling fallback is required for undocumented Steam APIs, make it bounded and adaptive: poll only around a likely context transition, stop after a stable capture, and retain the existing TTL fallback.
- Keep React Fiber inspection as a last-resort adapter behind the capture boundary.

## ✅ Acceptance Criteria
- [ ] The code implements the requested change.
- [ ] Existing unit tests still pass (no regressions).
- [ ] Add tests proving no perpetual interval runs while the QAM remains hidden.
- [ ] Add tests proving the last focused game is still available when the QAM opens.

## 🚫 AI Constraints & Scope Limits
- Do not refactor code outside of the specified function/file.
- Do not change the public API or return types of the affected functions.
- Do not add new third-party libraries.

---
name: Code Review Action Item
about: Address feedback from a code review or tackle technical debt
title: 'refactor: Make Settings the single source of truth in frontend state'
labels: 'tech-debt, code-review'
assignees: ''
---

## 🔍 The Review Finding
**Reviewer Comment / Rationale:**
> "`LudusaviStateSnapshot` stores `selectedGame`, `autoSyncNotificationsEnabled`, and `notificationSettings` separately from the same values in `settings`. Some setters update both copies, `setSelectedGame()` updates only one, and `syncSelectedGameCache()` exists solely to repair the divergence. This duplicates authority and forces every caller to remember which mutation path preserves the invariant."

## 📍 Exact Location
- **Original PR (if applicable):** #
- **File(s):** `src/state/ludusaviState.tsx`, `src/components/qam/LudusaviContent.tsx`, `src/controllers/gameLifecycleController.tsx`
- **Function/Class/Lines:** `LudusaviStateSnapshot` lines 62-75; `applySettings()` lines 127-136; `setSelectedGame()` and `syncSelectedGameCache()` lines 138-147; notification/auto-sync setters lines 149-178; QAM cache synchronization lines 143-145, 428-499

## 🛠️ Requested Change
- Store each setting once in `settings`.
- Preserve existing snapshot-facing names with derived selectors/getters if required, but eliminate independently mutable duplicate values and `syncSelectedGameCache()`.
- Make every optimistic setting update patch the authoritative settings object through one typed store method.

## ✅ Acceptance Criteria
- [ ] The code implements the requested change.
- [ ] Existing unit tests still pass (no regressions).
- [ ] Add invariant tests proving selected game, notification policy, and auto-sync status cannot diverge from `settings`.
- [ ] Callers no longer need paired `setSelectedGame()` and `syncSelectedGameCache()` calls.

## 🚫 AI Constraints & Scope Limits
- Do not refactor code outside of the specified function/file.
- Do not change the public API or return types of the affected functions.
- Do not add new third-party libraries.

---
name: Code Review Action Item
about: Address feedback from a code review or tackle technical debt
title: 'refactor: Extract explicit start and exit lifecycle transactions'
labels: 'tech-debt, code-review'
assignees: ''
---

## 🔍 The Review Finding
**Reviewer Comment / Rationale:**
> "`handleAppStart()` and `handleAppExit()` are long transaction coordinators with nested result branching, status publication, process suspension, Syncthing ownership transfer, notifications, history synchronization, and cleanup flags. Correct cleanup depends on mutable booleans such as `paused`, `retainPreGameWatch`, and `handoffTransferred`. Feature-specific behavior is being inserted directly into these paths, increasing the chance that a new result branch misses status, resume, watch cancellation, or history cleanup."

## 📍 Exact Location
- **Original PR (if applicable):** #
- **File(s):** `src/controllers/gameLifecycleController.tsx`, `src/controllers/gameLifecycleController.test.ts`, `src/controllers/gameLifecycleController.logging.test.ts`
- **Function/Class/Lines:** `handleAppStart()` lines 205-380; conflict branch lines 296-350; `handleAppExit()` lines 382-535; Syncthing handoff switch lines 443-506

## 🛠️ Requested Change
- Extract start and exit workflows into explicit transaction objects or pure decision functions that return commands/effects.
- Centralize terminal cleanup for process resume, watch cancellation/transfer, status completion/hide, and history synchronization.
- Replace duplicated silent-reason and result-status branches with typed policy tables.

## ✅ Acceptance Criteria
- [ ] The code implements the requested change.
- [ ] Existing unit tests still pass (no regressions).
- [ ] Add table-driven tests covering every lifecycle result status and every cleanup obligation.
- [ ] No terminal path can leave a paused process or unowned Syncthing watch.

## 🚫 AI Constraints & Scope Limits
- Do not refactor code outside of the specified function/file.
- Do not change the public API or return types of the affected functions.
- Do not add new third-party libraries.

---
name: Code Review Action Item
about: Address feedback from a code review or tackle technical debt
title: 'refactor: Decompose the QAM god component into testable workflows'
labels: 'tech-debt, code-review'
assignees: ''
---

## 🔍 The Review Finding
**Reviewer Comment / Rationale:**
> "`LudusaviContent` is an 858-line component that owns initial hydration, metadata caching, game-list refresh policy, Steam-context selection, settings controllers, log retrieval, manual backup/restore orchestration, snapshot restore orchestration, notifications, and final layout. The manual operation and snapshot restore paths duplicate the same logging, notifications, refresh, operation-status, log, history, and cleanup sequence. Rendering is no longer the component's primary responsibility."

## 📍 Exact Location
- **Original PR (if applicable):** #
- **File(s):** `src/components/qam/LudusaviContent.tsx` and new sibling QAM workflow modules/tests
- **Function/Class/Lines:** `LudusaviContent()` lines 77-858; initial load/metadata lines 253-390; game synchronization lines 392-499; manual refresh lines 501-566; `runForceOperation()` lines 628-710; `runSnapshotRestore()` lines 712-791

## 🛠️ Requested Change
- Extract initial-content loading, Steam-context selection, game refresh, and manual-operation execution into focused hooks/controllers with injected RPC dependencies.
- Use one manual-operation finalization pipeline for backup, latest restore, and snapshot restore.
- Reduce `LudusaviContent` to state selection, controller composition, and section rendering.

## ✅ Acceptance Criteria
- [ ] The code implements the requested change.
- [ ] Existing unit tests still pass (no regressions).
- [ ] Add unit tests for the extracted load, refresh, and manual-operation workflows without rendering the full QAM.
- [ ] Backup and both restore paths share one refresh/history/log completion implementation.

## 🚫 AI Constraints & Scope Limits
- Do not refactor code outside of the specified function/file.
- Do not change the public API or return types of the affected functions.
- Do not add new third-party libraries.

---
name: Code Review Action Item
about: Address feedback from a code review or tackle technical debt
title: 'refactor: Split PluginUpdater by release, cooldown, and install-ledger responsibility'
labels: 'tech-debt, code-review'
assignees: ''
---

## 🔍 The Review Finding
**Reviewer Comment / Rationale:**
> "`PluginUpdater` and its module span 928 lines and combine version parsing, GitHub release filtering, manifest validation, candidate selection, rate-limit parsing, cached-check policy, mutable persistence payloads, pending-install lifecycle, and startup reconciliation. The 403/429 cooldown block is duplicated in `check_for_update()` and `revalidate()`. This is a multi-owner module: release discovery and install-ledger correctness can change independently but currently share one mutable class and lock."

## 📍 Exact Location
- **Original PR (if applicable):** #
- **File(s):** `py_modules/sdh_ludusavi/updater.py`, `py_modules/sdh_ludusavi/updater_models.py`, `tests/test_updater.py`, `tests/test_updater_service.py`, `tests/test_updater_lazy.py`
- **Function/Class/Lines:** release parsing/selection lines 33-306; `PluginUpdater` lines 309-928; `check_for_update()` lines 437-673; `revalidate()` lines 675-838; pending-install methods lines 840-928

## 🛠️ Requested Change
- Separate pure release parsing/selection, remote release validation, cooldown policy, and pending-install ledger into focused modules/classes.
- Extract one rate-limit response parser used by both check and revalidation.
- Keep `PluginUpdater` as a small façade coordinating those collaborators and persistence.

## ✅ Acceptance Criteria
- [ ] The code implements the requested change.
- [ ] Existing unit tests still pass (no regressions).
- [ ] Existing public service/RPC behavior remains unchanged.
- [ ] Rate-limit and pending-install state transitions are independently unit-tested without constructing the full updater.

## 🚫 AI Constraints & Scope Limits
- Do not refactor code outside of the specified function/file.
- Do not change the public API or return types of the affected functions.
- Do not add new third-party libraries.

---
name: Code Review Action Item
about: Address feedback from a code review or tackle technical debt
title: 'refactor: Centralize backend backup and restore execution bookkeeping'
labels: 'tech-debt, code-review'
assignees: ''
---

## 🔍 The Review Finding
**Reviewer Comment / Rationale:**
> "`GameLifecycleManager` repeats the same operation skeleton across conflict backup/restore, launch restore, exit backup, force backup, force restore, and snapshot restore: acquire the operation lock, invoke an adapter method, record success/failure history, refresh the registry, log, and shape a result. The duplicated branches already differ subtly in refresh behavior and `Same` handling. This is policy duplication around the most stateful backend operations."

## 📍 Exact Location
- **Original PR (if applicable):** #
- **File(s):** `py_modules/sdh_ludusavi/lifecycle.py`, `tests/test_lifecycle.py`, `tests/test_history_integration.py`, `tests/test_backup_browser.py`
- **Function/Class/Lines:** `resolve_game_start_conflict()` lines 191-244; `restore_game_on_start()` lines 246-280; `backup_game_on_exit()` lines 350-384; `force_backup()` lines 393-441; `force_restore()` lines 443-492; `restore_backup_version()` lines 505-568

## 🛠️ Requested Change
- Introduce one private operation executor that accepts operation type, trigger, adapter callback, and result-shaping policy.
- Centralize success/failure history recording and registry refresh rules.
- Keep lifecycle eligibility and recency decisions in their existing public methods.

## ✅ Acceptance Criteria
- [ ] The code implements the requested change.
- [ ] Existing unit tests still pass (no regressions).
- [ ] Add table-driven tests proving consistent history, refresh, and failure behavior for every backup/restore trigger.
- [ ] Operation-specific result payloads remain unchanged.

## 🚫 AI Constraints & Scope Limits
- Do not refactor code outside of the specified function/file.
- Do not change the public API or return types of the affected functions.
- Do not add new third-party libraries.

---
name: Code Review Action Item
about: Address feedback from a code review or tackle technical debt
title: 'refactor: Define quality gates once and reuse them everywhere'
labels: 'tech-debt, code-review'
assignees: ''
---

## 🔍 The Review Finding
**Reviewer Comment / Rationale:**
> "The same lint, format, type-check, test, frontend verification, packaging, and ZIP validation sequence is manually duplicated across CI, stable release, development release, and local hooks. The copies already diverge: CI/release use `./run.sh pnpm run verify`, while pre/post-commit scripts invoke pnpm directly. Every tool or flag change now requires synchronized edits across multiple shell and YAML surfaces."

## 📍 Exact Location
- **Original PR (if applicable):** #
- **File(s):** `.github/workflows/ci.yml`, `.github/workflows/release.yml`, `.github/workflows/dev-release.yml`, `scripts/pre_commit.sh`, `scripts/post_commit.sh`, `scripts/orchestration/run-quality-gates`
- **Function/Class/Lines:** CI quality/package steps lines 30-60; stable release lines 77-105; development release lines 85-113; local hook command sequences

## 🛠️ Requested Change
- Define check-mode quality gates in one repository script or composite action and call it from CI and both release workflows.
- Define the local fix-mode variant once for pre-commit.
- Route all project tooling, including pnpm verification, through `./run.sh`.

## ✅ Acceptance Criteria
- [ ] The code implements the requested change.
- [ ] Existing unit tests still pass (no regressions).
- [ ] CI, stable release, development release, and local hooks invoke the same authoritative gate implementation.
- [ ] A test or static assertion prevents workflows from reintroducing duplicated inline gate sequences.

## 🚫 AI Constraints & Scope Limits
- Do not refactor code outside of the specified function/file.
- Do not change the public API or return types of the affected functions.
- Do not add new third-party libraries.

---
name: Code Review Action Item
about: Address feedback from a code review or tackle technical debt
title: 'refactor: Unify atomic JSON persistence and report the correct failing source'
labels: 'tech-debt, code-review'
assignees: ''
---

## 🔍 The Review Finding
**Reviewer Comment / Rationale:**
> "`JsonSettingsStore.write()` and `PersistenceManager.save_cache()` duplicate the same temp-file, JSON serialization, `os.replace`, and cleanup sequence. More importantly, `_warn_load()` always reports the cache path, even when the settings store failed. That produces false diagnostics during settings corruption or I/O failures and makes persistence incidents harder to identify."

## 📍 Exact Location
- **Original PR (if applicable):** #
- **File(s):** `py_modules/sdh_ludusavi/persistence.py`, `tests/test_persistence.py`
- **Function/Class/Lines:** `JsonSettingsStore.write()` lines 103-114; `PersistenceManager._load_all_locked()` lines 152-181; `save_cache()` lines 188-201; `_warn_load()` lines 203-205

## 🛠️ Requested Change
- Extract one private atomic JSON writer used by both settings and cache persistence.
- Pass explicit source/path context to load warnings so settings failures never identify the cache file.
- Preserve existing locking and atomic replacement behavior.

## ✅ Acceptance Criteria
- [ ] The code implements the requested change.
- [ ] Existing unit tests still pass (no regressions).
- [ ] Add tests asserting the logged source for malformed settings and malformed cache inputs.
- [ ] Add shared atomic-write failure tests covering temp-file cleanup for both destinations.

## 🚫 AI Constraints & Scope Limits
- Do not refactor code outside of the specified function/file.
- Do not change the public API or return types of the affected functions.
- Do not add new third-party libraries.
