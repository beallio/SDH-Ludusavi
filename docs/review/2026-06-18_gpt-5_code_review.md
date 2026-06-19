---
name: Code Review Action Item
about: Address feedback from a code review or tackle technical debt
title: 'refactor: authorize and bind process signaling to the launched game'
labels: 'tech-debt, code-review'
assignees: ''
---

## 🔍 The Review Finding
**Reviewer Comment / Rationale:**
> "`pause_game_process` and `resume_game_process` accept any numeric PID greater than 1, enumerate its descendants, and send SIGSTOP/SIGCONT without proving that the PID is the Steam-launched game identified by the lifecycle event. A compromised or faulty frontend can suspend unrelated same-user processes, and PID reuse can redirect a later resume signal to a different process."

## 📍 Exact Location
- **Original PR (if applicable):** #
- **File(s):** `main.py`, `py_modules/sdh_ludusavi/watchdog.py`
- **Function/Class/Lines:** `Plugin.pause_game_process` / `Plugin.resume_game_process` (`main.py:190-198`); `ProcessWatchdog.pause` / `resume`, `_coerce_signal_pid`, `_send_signal_tree`, `_process_tree` (`watchdog.py:41-92`, `178-253`)

## 🛠️ Requested Change
- Validate that the target PID belongs to the expected Steam game process tree before signaling it.
- Capture process identity data such as UID and `/proc/<pid>/stat` start time when pausing, and require the same identity when resuming.
- Permit resume operations only for process identities previously paused by this watchdog.

## ✅ Acceptance Criteria
- [ ] The code implements the requested change.
- [ ] Existing unit tests still pass (no regressions).
- [ ] Add tests proving arbitrary same-user processes are rejected.
- [ ] Add a PID-reuse test proving a different process with the same numeric PID is never signaled.
- [ ] Add a test proving descendants are signaled only while the root process identity remains valid.

## 🚫 AI Constraints & Scope Limits
- Do not refactor code outside of the specified function/file.
- Do not change the public API or return types of the affected functions.
- Do not add new third-party libraries.

---
name: Code Review Action Item
about: Address feedback from a code review or tackle technical debt
title: 'refactor: pin release workflow dependencies and tool versions'
labels: 'tech-debt, code-review'
assignees: ''
---

## 🔍 The Review Finding
**Reviewer Comment / Rationale:**
> "CI and release jobs execute actions through mutable major-version tags, and `setup-uv` installs `latest`. The release workflows grant `contents: write`, so an upstream action-tag compromise or an unreviewed tool release can execute with release-writing authority. The current tests explicitly enforce mutable tags rather than immutable revisions."

## 📍 Exact Location
- **Original PR (if applicable):** #
- **File(s):** `.github/workflows/ci.yml`, `.github/workflows/dev-release.yml`, `.github/workflows/release.yml`, `tests/test_release_workflows.py`
- **Function/Class/Lines:** All `uses:` declarations (`ci.yml:19-20`, `24-30`, `39-40`, `50-58`, `96-97`; `dev-release.yml:51-55`, `76-110`, `153-154`; `release.yml:47-50`, `72-106`, `141-142`); workflow assertions (`test_release_workflows.py:163-187`)

## 🛠️ Requested Change
- Pin every external GitHub Action to a reviewed full commit SHA and retain the release tag in a comment for maintainability.
- Pin `uv` to an explicit reviewed version instead of `latest`.
- Declare least-privilege permissions per job, keeping `contents: write` only where publishing requires it.
- Update workflow tests to reject mutable action references and floating tool versions.

## ✅ Acceptance Criteria
- [ ] The code implements the requested change.
- [ ] Existing unit tests still pass (no regressions).
- [ ] Add tests that fail when an external action is referenced by a mutable tag.
- [ ] Add a test that fails when a release tool version is set to `latest`.
- [ ] CI jobs that do not publish have explicit read-only permissions.

## 🚫 AI Constraints & Scope Limits
- Do not refactor code outside of the specified function/file.
- Do not change the public API or return types of the affected functions.
- Do not add new third-party libraries.

---
name: Code Review Action Item
about: Address feedback from a code review or tackle technical debt
title: 'refactor: reject ambiguous fuzzy game matches'
labels: 'tech-debt, code-review'
assignees: ''
---

## 🔍 The Review Finding
**Reviewer Comment / Rationale:**
> "Fuzzy matching returns the first substring match in container iteration order. The same input can therefore resolve to different games when registry order changes. This was reproduced with `Portal`, which resolved to either `Portal 2` or `Portal Stories: Mel` solely from dictionary order. In an autosync path, an ambiguous match can target the wrong save set for backup or restore."

## 📍 Exact Location
- **Original PR (if applicable):** #
- **File(s):** `py_modules/sdh_ludusavi/matcher.py`, `src/state/ludusaviState.tsx`
- **Function/Class/Lines:** `GameRegistryMatcher.match_game` fuzzy branch (`matcher.py:83-90`); `LudusaviStateStore.isTracked` substring branch (`ludusaviState.tsx:221-249`)

## 🛠️ Requested Change
- Collect all eligible fuzzy candidates instead of returning the first match.
- Accept a fuzzy result only when it is uniquely identifiable by a deterministic rule; otherwise return no match and require AppID, alias, or exact-name resolution.
- Keep frontend tracked-state classification aligned with the backend ambiguity rules so the launch gate is not activated for a game the backend will reject.

## ✅ Acceptance Criteria
- [ ] The code implements the requested change.
- [ ] Existing unit tests still pass (no regressions).
- [ ] Add tests with two valid substring candidates in both insertion orders and verify the result is identical.
- [ ] Add a test proving ambiguous candidates return no match.
- [ ] Preserve existing AppID, alias, and exact normalized-name matching behavior.

## 🚫 AI Constraints & Scope Limits
- Do not refactor code outside of the specified function/file.
- Do not change the public API or return types of the affected functions.
- Do not add new third-party libraries.

---
name: Code Review Action Item
about: Address feedback from a code review or tackle technical debt
title: 'refactor: prevent late settings responses from reverting newer state'
labels: 'tech-debt, code-review'
assignees: ''
---

## 🔍 The Review Finding
**Reviewer Comment / Rationale:**
> "A timed-out settings RPC is not cancelled. The queue advances to later mutations, but the late-resolution handler can subsequently call `applySettings` with the entire stale response object. Sequence counters are isolated per setting, so an old auto-sync response can overwrite a newer update-channel, notification, or selected-game value. A targeted Vitest reproduced the newer channel being reverted after the timed-out response arrived."

## 📍 Exact Location
- **Original PR (if applicable):** #
- **File(s):** `src/settings/settingsMutationRuntime.ts`, `src/settings/settingsMutationRuntime.test.ts`
- **Function/Class/Lines:** `withTimeout`, `applySettings`, and per-setting late-resolution handlers in `createSettingsMutationRuntime` (`settingsMutationRuntime.ts:115-145`, `201-249`, `263-311`, `324-433`, `462-511`)

## 🛠️ Requested Change
- Introduce one runtime-wide mutation generation or equivalent reconciliation rule across all settings.
- Do not apply a full settings snapshot from a response that predates any newer mutation.
- Merge only the field owned by the completed mutation, or fetch a fresh authoritative settings snapshot before applying a late response.

## ✅ Acceptance Criteria
- [ ] The code implements the requested change.
- [ ] Existing unit tests still pass (no regressions).
- [ ] Add a test where one setting times out, another setting succeeds, and the first response resolves late without reverting the second.
- [ ] Add equivalent coverage for selected-game and notification mutations.
- [ ] Optimistic rollback behavior remains intact for genuine RPC failures.

## 🚫 AI Constraints & Scope Limits
- Do not refactor code outside of the specified function/file.
- Do not change the public API or return types of the affected functions.
- Do not add new third-party libraries.

---
name: Code Review Action Item
about: Address feedback from a code review or tackle technical debt
title: 'refactor: abort installation when pending-state persistence fails'
labels: 'tech-debt, code-review'
assignees: ''
---

## 🔍 The Review Finding
**Reviewer Comment / Rationale:**
> "`Plugin._call` converts backend exceptions into resolved `{status: 'failed'}` payloads, but the update controller ignores the return value from `recordUpdateInstallRequestedCall`, logs success, and invokes Decky's installer anyway. A disk or persistence failure can therefore start an update without durable pending-install metadata, breaking reconciliation and allowing repeated or misleading update state."

## 📍 Exact Location
- **Original PR (if applicable):** #
- **File(s):** `main.py`, `src/api/ludusaviRpc.ts`, `src/controllers/pluginUpdateController.tsx`
- **Function/Class/Lines:** `Plugin._call` (`main.py:414-439`); `recordUpdateInstallRequestedCall` declaration (`ludusaviRpc.ts:82-86`); `usePluginUpdateController.install` (`pluginUpdateController.tsx:382-494`, especially `410-437`)

## 🛠️ Requested Change
- Treat the record-pending RPC as an `RpcResult` and validate it before entering the post-install guard or calling Decky's installer.
- Abort the install flow on a failed/skipped response and surface the backend message.
- Apply the same response validation to handoff confirmation and pending-state cleanup where their result affects controller state.

## ✅ Acceptance Criteria
- [ ] The code implements the requested change.
- [ ] Existing unit tests still pass (no regressions).
- [ ] Add a controller test proving a failed record-pending response prevents any installer invocation.
- [ ] Add a test proving the UI exits the installing state and displays the persistence error.
- [ ] Successful record, installer handoff, and confirmation behavior remains unchanged.

## 🚫 AI Constraints & Scope Limits
- Do not refactor code outside of the specified function/file.
- Do not change the public API or return types of the affected functions.
- Do not add new third-party libraries.

---
name: Code Review Action Item
about: Address feedback from a code review or tackle technical debt
title: 'refactor: fail closed when the state lock cannot be acquired'
labels: 'tech-debt, code-review'
assignees: ''
---

## 🔍 The Review Finding
**Reviewer Comment / Rationale:**
> "The inter-process lock logs a timeout and returns `None`, after which callers continue reading and writing without exclusion. This defeats the lock exactly during duplicate-backend contention. The behavior was reproduced by holding the lock externally: `save_cache` timed out and still replaced the cache file. Atomic rename prevents partial JSON, but it does not prevent lost updates or stale reconciliation."

## 📍 Exact Location
- **Original PR (if applicable):** #
- **File(s):** `py_modules/sdh_ludusavi/persistence.py`, `tests/test_persistence.py`
- **Function/Class/Lines:** `_InterProcessLock.__enter__` and `_acquire_file_lock` (`persistence.py:36-77`); persistence read/write callers (`persistence.py:145-235`)

## 🛠️ Requested Change
- Make lock acquisition failure explicit and fail closed for state reads, writes, and compound reconciliation.
- Propagate a bounded lock-timeout error to the caller instead of proceeding without exclusion.
- Preserve atomic temp-file replacement after the lock is successfully acquired.

## ✅ Acceptance Criteria
- [ ] The code implements the requested change.
- [ ] Existing unit tests still pass (no regressions).
- [ ] Add a contention test proving a timed-out writer does not modify the state file.
- [ ] Add a test proving lock timeout is reported through the existing RPC failure path.
- [ ] Reentrant locking and normal multi-thread serialization continue to pass.

## 🚫 AI Constraints & Scope Limits
- Do not refactor code outside of the specified function/file.
- Do not change the public API or return types of the affected functions.
- Do not add new third-party libraries.

---
name: Code Review Action Item
about: Address feedback from a code review or tackle technical debt
title: 'refactor: keep blocking Syncthing work outside the manager lock'
labels: 'tech-debt, code-review'
assignees: ''
---

## 🔍 The Review Finding
**Reviewer Comment / Rationale:**
> "`SyncthingWatchManager.start_watch` holds the manager mutex while performing credential discovery and multiple network calls, and stop paths hold it while joining threads. Polling or stopping an existing watch is blocked behind unrelated I/O. A targeted concurrency check confirmed that polling an active watch could not complete while a new watch was stalled in credential resolution."

## 📍 Exact Location
- **Original PR (if applicable):** #
- **File(s):** `py_modules/sdh_ludusavi/syncthing/watcher.py`, `tests/test_watcher.py`
- **Function/Class/Lines:** `SyncthingWatchManager.start_watch`, `stop_watch`, and `stop_all` (`watcher.py:287-403`, `424-436`)

## 🛠️ Requested Change
- Perform credential discovery, folder resolution, and peer probes outside the manager lock.
- Use a short locked commit phase to replace a same-signature watch and register the prepared watch.
- Remove watches under the lock, then stop/join them after releasing it.
- Handle concurrent same-signature starts deterministically.

## ✅ Acceptance Criteria
- [ ] The code implements the requested change.
- [ ] Existing unit tests still pass (no regressions).
- [ ] Add a concurrency test proving a stalled watch startup does not block polling or stopping an existing watch.
- [ ] Add a test proving `stop_all` does not hold the manager lock while joining watch threads.
- [ ] Same-signature replacement still leaves exactly one registered watch.

## 🚫 AI Constraints & Scope Limits
- Do not refactor code outside of the specified function/file.
- Do not change the public API or return types of the affected functions.
- Do not add new third-party libraries.

---
name: Code Review Action Item
about: Address feedback from a code review or tackle technical debt
title: 'refactor: bound backup-browser filesystem inspection'
labels: 'tech-debt, code-review'
assignees: ''
---

## 🔍 The Review Finding
**Reviewer Comment / Rationale:**
> "Opening the backup browser calculates size and file count for every snapshot synchronously. Directory snapshots recursively stat every file, and ZIP snapshots load every central-directory entry. The work scales with all retained backup contents, runs inside the global Ludusavi operation lock, and delays both the modal and unrelated backup/restore operations."

## 📍 Exact Location
- **Original PR (if applicable):** #
- **File(s):** `py_modules/sdh_ludusavi/ludusavi.py`, `tests/test_backup_browser.py`
- **Function/Class/Lines:** `PyludusaviAdapter.list_backups` and `_backup_disk_stats` (`ludusavi.py:300-345`, `494-557`)

## 🛠️ Requested Change
- Remove unbounded recursive inspection from the initial backup-list request.
- Use existing metadata where available and apply a strict time, entry-count, or snapshot-count budget for optional filesystem statistics.
- Return the existing nullable size/count fields as unknown when the budget is exceeded rather than blocking the operation.

## ✅ Acceptance Criteria
- [ ] The code implements the requested change.
- [ ] Existing unit tests still pass (no regressions).
- [ ] Add tests with large directory and ZIP entry counts proving inspection is bounded.
- [ ] Add a test proving the backup list still returns all snapshot identities when statistics are unavailable.
- [ ] The return schema and restore identifiers remain unchanged.

## 🚫 AI Constraints & Scope Limits
- Do not refactor code outside of the specified function/file.
- Do not change the public API or return types of the affected functions.
- Do not add new third-party libraries.
