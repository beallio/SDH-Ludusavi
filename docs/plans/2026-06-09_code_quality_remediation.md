# Phased Code-Quality Remediation Plan

## Problem Definition

The code-quality audit in
`docs/review/2026-06-08_thermo_nuclear_code_quality_review.md` identified valid
maintainability pressure in four areas:

1. Updater state and orchestration are distributed across `main.py`,
   `service.py`, and `updater.py`, with direct access to private service fields.
2. Game-name whitespace sanitization is duplicated in three backend modules.
3. Steam private runtime APIs are accessed through scattered inline `any` casts.
4. Several frontend modules and one test suite combine too many responsibilities.

This plan implements those findings as behavior-preserving refactors. It does not
change RPC names, persisted keys, updater selection rules, visible UI behavior, or
release behavior.

`main.py::_run_blocking` is explicitly excluded. Its self-pipe implementation is
an intentional, previously validated runtime design and is not generic refactoring
debt.

## Architecture Overview

The implementation is divided into independently reviewable phases:

1. Freeze current behavior with characterization tests.
2. Separate updater models and GitHub transport.
3. Place updater state and orchestration under one typed `PluginUpdater`.
4. Centralize game-name sanitization.
5. Centralize Steam runtime validation and updater RPC types.
6. Decompose large frontend modules by responsibility.
7. Split the large Syncthing test suite and add architecture budgets.
8. Update architecture documentation and run the complete review gate.

The target updater flow is:

```text
Decky RPC in main.py
        |
        v
SDHLudusaviService facade
        |
        v
PluginUpdater
  |       |        |
  |       |        +--> updater persistence snapshot
  |       +-----------> GitHubReleaseClient
  +-------------------> pure updater models and selection functions
```

The target frontend runtime flow is:

```text
Steam/Decky private globals
        |
        v
steamRuntime.ts runtime guards
        |
        +--> steam.ts domain parsing
        +--> steamLifecycleSource.ts
        +--> autoSyncStatusBrowserView.ts
        +--> launcher/artwork adapters
```

## Core Data Structures

### Backend Updater Models

Create typed updater models instead of passing unvalidated dictionaries through
all layers:

```python
@dataclass(frozen=True)
class JsonResponse:
    status: int
    headers: Mapping[str, str]
    body: object


@dataclass(frozen=True)
class ReleaseManifest:
    schema_version: int
    plugin_name: str
    package_name: str
    version: str
    source_version: str
    tag: str
    channel: Literal["stable", "dev"]
    asset_name: str
    sha256: str
    generated_at: str


@dataclass(frozen=True)
class UpdateCandidate:
    version: str
    tag: str
    channel: Literal["stable", "development"]
    artifact_url: str
    sha256: str
    release_url: str
    published_at: str
    action: Literal["update", "move_to_stable", "downgrade_to_stable"]
```

Define a typed updater cache model that:

- normalizes known fields;
- rejects malformed known values individually;
- retains unknown fields in an `extras` mapping;
- emits the existing JSON field names;
- never persists rate-limit expiration.

### Frontend Updater Types

Add complete frontend contracts:

```typescript
export type PendingUpdateInstall = {
  version: string;
  tag: string;
  channel: UpdateChannel;
  published_at: string;
  requested_at: string;
  handoff_confirmed_at?: string;
  update_trace_id?: string | null;
};

export type UpdateCheckContext = {
  update_channel: UpdateChannel;
  automatic_update_checks: boolean;
  installed_version: string;
  effective_installed_version: string;
  last_checked_at: string | null;
  last_checked_channel: UpdateChannel | null;
  last_available_tag: string | null;
  last_notified_tag: string | null;
  installed_release_tag: string | null;
  installed_release_published_at: string | null;
  pending_update_install: PendingUpdateInstall | null;
  rate_limited_until: string | null;
};

export type UpdateInstallRequest =
  PluginUpdateCandidate & { updateTraceId: string };
```

### Steam Runtime Types

Steam private APIs are unstable runtime data. They must enter the application as
`unknown` and be narrowed through guards:

```typescript
export function asRecord(
  value: unknown,
): Record<string, unknown> | null {
  return typeof value === "object" && value !== null
    ? value as Record<string, unknown>
    : null;
}
```

Ambient declarations must describe only stable contracts already verified at
runtime. They must not claim that optional Steam internals always exist.

## Public Interfaces

### Unchanged Backend RPC Contract

The following RPC names and wire payloads remain unchanged:

```text
set_update_channel
set_automatic_update_checks
get_update_check_context
check_for_plugin_update
revalidate_plugin_update
record_update_install_requested
confirm_update_install_handoff
clear_pending_update_install
```

### `PluginUpdater`

The stateful updater interface is:

```python
class PluginUpdater:
    def load_state(
        self,
        settings: Mapping[str, object],
        cache: Mapping[str, object],
    ) -> None: ...

    def settings_payload(self) -> dict[str, object]: ...
    def cache_payload(self) -> dict[str, object]: ...

    def set_channel(self, channel: str) -> None: ...
    def set_automatic_checks(self, enabled: bool) -> None: ...
    def get_context(self) -> dict[str, object]: ...

    def check_for_update(
        self,
        current_version: str,
        force: bool = False,
    ) -> dict[str, object]: ...

    def revalidate(
        self,
        candidate: Mapping[str, object],
    ) -> dict[str, object]: ...

    def record_install_requested(
        self,
        candidate: Mapping[str, object],
    ) -> dict[str, object]: ...

    def confirm_install_handoff(self, version: str) -> dict[str, object]: ...
    def clear_pending_install(self, version: str | None = None) -> dict[str, object]: ...
    def reconcile_pending_install(self, current_version: str) -> None: ...
    def has_pending_install(self) -> bool: ...
```

`PluginUpdater` receives narrow dependencies only. It must not receive or import
`SDHLudusaviService`.

### Release Client

```python
class ReleaseClient(Protocol):
    def list_releases(self) -> JsonResponse: ...
    def get_release(self, tag: str) -> JsonResponse: ...
    def get_manifest(self, url: str) -> JsonResponse: ...
```

### Frontend Controller

```typescript
export type PluginUpdateController = {
  effectiveCurrentVersion: string;
  candidate: PluginUpdateCandidate | null;
  checkResult: UpdateCheckResult | null;
  errorMessage: string | null;
  isChecking: boolean;
  isInstalling: boolean;
  isHandoffPending: boolean;
  installedReleasePublishedAt: string | null;
  checkNow(): Promise<void>;
  install(candidate: PluginUpdateCandidate): Promise<void>;
};
```

### Steam Lifecycle Source

```typescript
export type SteamLifecycleSource = {
  start(): void;
  dispose(): void;
};

export function createSteamLifecycleSource(options: {
  onStart(name: string, appID: string, instanceID?: number): void;
  onExit(name: string, appID: string): void;
  log(level: string, message: string): void;
  runtime?: SteamLifecycleRuntime;
}): SteamLifecycleSource;
```

## Dependency Requirements

- Add no Python or frontend dependencies.
- Continue using Python standard-library `urllib.request`.
- Use existing React, Vitest, pytest, Ruff, and `ty` tooling.
- Run every project command through `./run.sh`.
- Keep caches and temporary state under `/tmp/sdh_ludusavi`.

## Fixed Assumptions

1. Implementation starts from local `main` at or after commit `85baf86`.
2. Work occurs on `refactor/code-quality-boundaries`.
3. No release, tag, workflow dispatch, push, or merge is permitted.
4. Package and plugin versions do not change.
5. Existing RPC names and JSON field names remain unchanged.
6. Existing settings keys remain `update_channel` and
   `automatic_update_checks`.
7. Existing cache key remains `update_check_cache`; no migration is required.
8. Unknown updater-cache fields survive load/save round trips.
9. Invalid known cache fields are discarded individually.
10. GitHub rate-limit expiration remains in memory only.
11. Successful update results remain cached for 24 hours.
12. Pending-install freshness remains 15 minutes.
13. Manual checks bypass successful-result caching but not active rate limits.
14. Failed checks never replace the last successful result.
15. Existing updater selection and revalidation rules remain unchanged.
16. Existing UI text, notifications, timings, and install workflow remain unchanged.
17. Steam private APIs are optional and unstable at runtime.
18. Runtime adapters validate private APIs from `unknown`.
19. This work addresses production Steam boundary casts, not every unrelated
    `any` in the frontend.
20. README changes are unnecessary because user behavior does not change.
21. `DEVELOPMENT.md` must reflect new internal ownership.
22. Every behavior-changing slice follows Red-Green-Refactor.
23. Refactor-only moves receive characterization or architecture tests first.
24. Each phase is committed separately with Conventional Commits.
25. Implementation proceeds without requesting product direction.
26. Stop only if baseline validation fails for a non-network reason or user-owned
    changes overlap required files.
27. Registry DNS failures during `pnpm audit` are reported separately from local
    frontend validation.
28. Unrelated user work is never formatted, staged, committed, reverted, or
    overwritten.

## Phase 0: Baseline and Contract Freeze

### Task 0.1: Verify Repository State

Run:

```bash
pwd
ls
git status --short --branch
git log -1 --oneline
```

Confirm Project Mode, wrapper configuration, clean tracked state, current commit,
and cache isolation.

### Task 0.2: Create the Feature Branch

Create:

```text
refactor/code-quality-boundaries
```

Commit this plan before implementation:

```text
docs(plan): define phased code quality remediation
```

### Task 0.3: Record the Baseline

Run:

```bash
./run.sh uv run ruff check .
./run.sh uv run ruff format --check .
./run.sh uv run ty check py_modules/sdh_ludusavi/
./run.sh uv run pytest
./run.sh pnpm run test:unit
./run.sh pnpm run typecheck
./run.sh pnpm run build
git diff --check
```

Append the branch, commit, test counts, and relevant file line counts to this
document before implementation.

## Phase 1: Updater Models and GitHub Boundary

### Task 1.1: Add Characterization Tests

Before moving implementation, cover:

- stable, development, legacy development, and local-build versions;
- candidate selection and ordering;
- manifest parsing and validation;
- malformed GitHub payloads;
- missing, duplicate, or mismatched assets;
- rate-limit header precedence;
- network and malformed JSON failures;
- revalidation equality checks;
- prohibition on logging full SHA-256 values.

### Task 1.2: Create Typed Models

Create:

```text
py_modules/sdh_ludusavi/updater_models.py
tests/test_updater_models.py
```

Move and formalize:

- `ParsedPluginVersion`;
- `ReleaseManifest`;
- `UpdateCandidate`;
- `JsonResponse`;
- update channel and action aliases;
- pending-install state;
- updater cache state;
- update result payloads.

`JsonResponse.body` must be `object`, not `Any`.

`ReleaseManifest` must become an active parsing boundary:

```python
def parse_release_manifest(payload: object) -> ReleaseManifest | None:
    record = as_string_key_mapping(payload)
    if record is None:
        return None

    version = record.get("version")
    sha256 = record.get("sha256")
    if not isinstance(version, str):
        return None
    if not isinstance(sha256, str) or SHA256_PATTERN.fullmatch(sha256) is None:
        return None

    return ReleaseManifest(...)
```

### Task 1.3: Extract GitHub Transport

Create:

```text
py_modules/sdh_ludusavi/updater_client.py
tests/test_updater_client.py
```

`GitHubReleaseClient` owns only:

- URL construction;
- HTTP headers;
- finite timeouts;
- JSON decoding;
- status and response headers;
- transport errors converted to `JsonResponse`.

It must not know about service state, persistence, throttling policy, or UI
payloads.

### Task 1.4: Move Pure Release Logic

Keep these functions independent from `PluginUpdater`:

```python
def parse_plugin_version(version: str) -> ParsedPluginVersion | None: ...
def validate_release_candidate(
    release: object,
    client: ReleaseClient,
) -> UpdateCandidate | None: ...
def select_candidate(...) -> UpdateCandidate | None: ...
def retry_after_from_response(
    response: JsonResponse,
    now: datetime,
) -> datetime | None: ...
def verify_revalidated_candidate(
    expected: Mapping[str, object],
    actual: UpdateCandidate,
) -> UpdateCandidate: ...
```

`updater.py` re-exports established symbols where needed to avoid unnecessary
internal import breakage.

### Task 1.5: Validate and Commit

Run focused updater tests, Ruff, formatting checks, and `ty`.

Commit:

```text
refactor(updater): extract typed release models and client
```

## Phase 2: Stateful PluginUpdater Ownership

### Task 2.1: Add Failing Architecture Tests

Extend `tests/test_architecture.py` to require:

- updater modules do not import `service`;
- updater modules contain no `service: Any`;
- updater modules contain no private service access;
- `main.py` does not directly access updater state fields;
- `SDHLudusaviService` stores `PluginUpdater`, not raw updater state;
- one manager owns updater state and GitHub orchestration.

### Task 2.2: Implement `PluginUpdater`

Reduce `updater.py` to stateful orchestration and compatibility re-exports.

Constructor:

```python
class PluginUpdater:
    def __init__(
        self,
        *,
        state_lock: AbstractContextManager[object],
        save_callback: Callable[[], None],
        log_callback: Callable[[str, str], None],
        release_client: ReleaseClient,
        version_resolver: Callable[[], str],
        now: Callable[[], datetime],
        monotonic: Callable[[], float],
    ) -> None:
        ...
```

It owns:

- update channel;
- automatic-check preference;
- typed updater cache;
- transient rate-limit expiration;
- pending-install fast path;
- successful-result cache lookup;
- cache-bypass logging;
- release discovery;
- result recording;
- cooldown handling;
- install revalidation;
- install-request recording;
- handoff confirmation;
- pending-install clearing;
- startup reconciliation.

### Task 2.3: Make Updates Atomic

Successful checks update related cache fields under one lock and persist once:

```python
with self._state_lock:
    self._cache.last_checked_at = result.checked_at
    self._cache.last_checked_channel = self._channel
    self._cache.last_checked_version = current_version
    self._cache.last_result = result
    self._cache.last_available_tag = available_tag
    self._save_callback()
```

Failed checks may update transient cooldown but must not overwrite the last
successful result.

### Task 2.4: Normalize Malformed Persistence

Apply these rules:

- invalid channel becomes `"stable"`;
- non-boolean automatic-check preference becomes `True`;
- non-mapping updater cache becomes empty;
- malformed pending install becomes absent;
- malformed timestamps are stale;
- invalid `last_result` is discarded;
- unknown cache keys survive;
- transient cooldown starts as `None`.

### Task 2.5: Integrate with Service

Construct `_updater` with narrow dependencies:

```python
self._updater = PluginUpdater(
    state_lock=self._state_lock,
    save_callback=self._save_state,
    log_callback=lambda level, message: self.log(level, message),
    release_client=release_client or GitHubReleaseClient(),
    version_resolver=resolve_version,
    now=lambda: datetime.now(timezone.utc),
    monotonic=time.monotonic,
)
```

`_load_state()` delegates updater settings/cache parsing. `_save_state()` merges
the updater snapshots into the existing settings and cache payloads.

Service methods remain facade methods:

```python
def set_update_channel(self, channel: str) -> dict[str, object]:
    self._updater.set_channel(channel)
    return self.get_settings()


def check_for_plugin_update(
    self,
    current_version: str,
    force: bool = False,
) -> dict[str, object]:
    return self._updater.check_for_update(current_version, force)
```

Remove these service fields:

- `_update_channel`;
- `_automatic_update_checks`;
- `_update_check_cache`;
- `_update_rate_limited_until`.

### Task 2.6: Simplify `main.py`

`main.py` becomes an async offload adapter:

```python
async def check_for_plugin_update(
    self,
    current_version: str,
    force: bool = False,
) -> dict[str, object]:
    return await self._call(
        "check_for_plugin_update",
        lambda: self._service().check_for_plugin_update(current_version, force),
    )
```

Replace unload-time private cache access with a service facade method:

```python
has_pending = backend.has_pending_update_install()
```

`main.py` must no longer parse cache timestamps, inspect updater fields, implement
pending fast paths, discover releases, or record check results.

### Task 2.7: Rewrite Tests Around Boundaries

Organize tests as:

- pure model/client tests;
- `PluginUpdater` state-transition tests;
- service facade and persisted JSON integration tests;
- `Plugin` RPC offload tests;
- static architecture tests.

Replace direct assertions against removed service fields with manager state,
public contexts, or persisted payload assertions.

### Task 2.8: Validate and Commit

Run all backend quality gates.

Commit:

```text
refactor(updater): encapsulate updater state and orchestration
```

## Phase 3: Shared Game-Name Sanitization

### Task 3.1: Add Red Tests

Create `tests/test_game_names.py` covering:

- `None`;
- empty and whitespace-only strings;
- leading/trailing whitespace;
- tabs, newlines, and repeated spaces;
- preservation of case and punctuation.

### Task 3.2: Create the Canonical Utility

Create `py_modules/sdh_ludusavi/game_names.py`:

```python
def sanitize_game_name(name: str | None) -> str:
    if not name:
        return ""
    return " ".join(name.split())
```

Do not place this in `matcher.py`; matching normalization has different
semantics.

### Task 3.3: Replace Duplicates

Use the utility in:

- service selected-game updates;
- lifecycle RPC boundaries;
- registry targeted refresh.

Delete all three `_sanitize_name` definitions. Add an architecture assertion
that duplicate definitions do not return.

### Task 3.4: Validate and Commit

Commit:

```text
refactor(games): centralize game name sanitization
```

## Phase 4: Typed Frontend RPC and Steam Runtime Boundaries

### Task 4.1: Complete Updater RPC Types

Add the updater types described above to `src/types/index.ts`.

Move updater RPC callables to `src/api/ludusaviRpc.ts`. The component must not
define updater callables directly.

Use exact request/response types for:

- update checks;
- update contexts;
- revalidation;
- install recording;
- handoff confirmation;
- pending-install clearing.

### Task 4.2: Create the Runtime Validation Module

Create:

```text
src/utils/steamRuntime.ts
src/utils/steamRuntime.test.ts
```

Export narrow accessors for:

- Router main running app;
- Router running apps;
- gamepad main window and browser window;
- SteamClient Apps;
- appStore;
- appDetailsStore;
- collection-store apps;
- app-lifetime registration;
- BrowserView creation and destruction.

Dynamic methods are callable only after a function guard and must be bound to
their original receiver.

### Task 4.3: Adopt the Runtime Boundary

Replace direct casts in:

- `src/utils/steam.ts`;
- `src/controllers/gameLifecycleController.tsx`;
- `src/surfaces/autoSyncStatusSurface.tsx`;
- `src/ludusaviLauncher.ts`;
- `src/shortcutArtwork.ts`.

Prohibit:

```typescript
Router as any
(globalThis as any).SteamClient
(window as any).SteamClient
(globalThis as any).appStore
(window as any).appStore
```

Change installed-app results from `any[]` to `unknown[]`.

### Task 4.4: Test Runtime Drift

Cover:

- missing globals;
- malformed nested values;
- non-function methods;
- uppercase and lowercase BrowserView methods;
- synchronous and promised installed-app results;
- malformed Router app lists;
- unavailable lifetime registration;
- receiver binding.

### Task 4.5: Validate and Commit

Run frontend unit tests, typecheck, and build.

Commit:

```text
refactor(steam): centralize typed runtime boundaries
```

## Phase 5: Frontend Responsibility Decomposition

### Task 5.1: Extract the Plugin Update Controller

Create:

```text
src/controllers/pluginUpdateController.tsx
src/controllers/pluginUpdateController.test.ts
```

Move into `usePluginUpdateController`:

- check state and timeout ownership;
- in-flight check reuse;
- context hydration;
- stale-result suppression;
- optimistic installed-version override;
- automatic-check effects;
- candidate revalidation;
- pending-install recording;
- Decky installer handoff;
- rollback and confirmation;
- updater logging.

Keep in `PluginUpdateSection.tsx`:

- JSX;
- channel and downgrade confirmation modals;
- labels and status rendering;
- external release navigation.

Targets:

- component at or below 300 lines;
- controller at or below 500 lines.

### Task 5.2: Preserve Updater Edge Cases

Executable tests must preserve:

- late checks cannot update current state;
- timeout clears check ownership;
- pending hydration suppresses only the initial automatic check;
- manual checks remain available;
- successful handoff updates shared version state;
- rejected handoff clears pending state;
- stale candidates matching the effective version become current;
- dev-to-stable and downgrade wording;
- SHA-256 logging redaction.

### Task 5.3: Extract the Steam Lifecycle Source

Create:

```text
src/controllers/steamLifecycleSource.ts
src/controllers/steamLifecycleSource.test.ts
```

Move:

- active-session tracking;
- startup reconciliation;
- notification registration;
- duplicate-event suppression;
- session resolution;
- Router fallback polling;
- registration and interval cleanup.

Keep in `gameLifecycleController.tsx`:

- backup and restore orchestration;
- conflict handling;
- process pause/resume;
- Syncthing handoff;
- epoch guards;
- history synchronization.

Target the remaining lifecycle controller at or below 525 lines.

### Task 5.4: Split Status Rendering and BrowserView Ownership

Create:

```text
src/surfaces/autoSyncStatusRenderer.tsx
src/surfaces/autoSyncStatusBrowserView.ts
```

Renderer ownership:

- status labels;
- status predicates;
- icon selection and serialization;
- HTML escaping;
- final HTML rendering.

BrowserView ownership:

- creation;
- method normalization;
- native owner versus adapter distinction;
- bounds synchronization;
- URL loading;
- deferred synchronization;
- destruction and fallback destruction.

`autoSyncStatusSurface.tsx` retains:

- current status state;
- show/hide/sync timers;
- publication rules;
- completion mapping;
- reset API.

Re-export established public symbols from `autoSyncStatusSurface.tsx`.

Preserve the rule that SteamClient destruction receives the native owner, never
the normalized adapter.

Targets:

- surface at or below 350 lines;
- renderer at or below 300 lines;
- BrowserView module at or below 300 lines.

### Task 5.5: Validate and Commit

Commit:

```text
refactor(frontend): decompose updater lifecycle and status modules
```

## Phase 6: Test-Suite and Maintainability Guards

### Task 6.1: Split Syncthing Monitor Tests

Replace the monolithic test file with:

```text
src/controllers/syncthingMonitor.initialization.test.ts
src/controllers/syncthingMonitor.activity.test.ts
src/controllers/syncthingMonitor.failures.test.ts
```

Grouping:

- initialization: allocation, readiness, cursor, timeout, supersession;
- activity: buffering, upload, download, pending, completion, grace period;
- failures: unavailable states, polling rejection, cleanup, context leaks.

Create shared fixtures only where at least two suites need the same behavior.

### Task 6.2: Replace Brittle Static Assertions

Replace source-substring checks with executable Vitest tests where feasible.

Keep static tests for constraints runtime tests cannot prove:

- no direct Steam global casts outside `steamRuntime.ts`;
- no updater private-service access;
- no updater orchestration in `main.py`;
- module size budgets;
- no source patterns that log full SHA values.

### Task 6.3: Add Module Size Budgets

Create `tests/test_module_size_budgets.py`:

```python
BUDGETS = {
    "py_modules/sdh_ludusavi/updater.py": 500,
    "src/components/PluginUpdateSection.tsx": 300,
    "src/controllers/pluginUpdateController.tsx": 500,
    "src/controllers/gameLifecycleController.tsx": 525,
    "src/controllers/steamLifecycleSource.ts": 250,
    "src/surfaces/autoSyncStatusSurface.tsx": 350,
    "src/surfaces/autoSyncStatusRenderer.tsx": 300,
    "src/surfaces/autoSyncStatusBrowserView.ts": 300,
}
```

Each split Syncthing test file must remain below 450 physical lines.

### Task 6.4: Validate and Commit

Commit:

```text
test(architecture): enforce module boundaries and size budgets
```

## Phase 7: Documentation, Validation, and Review

### Task 7.1: Update Architecture Documentation

Update `DEVELOPMENT.md` with:

- `PluginUpdater` ownership;
- updater model/client/state separation;
- unchanged persistence contract;
- Steam runtime validation;
- frontend controller/source/surface ownership.

Do not describe new user-facing behavior.

### Task 7.2: Record the Session

Create:

```text
docs/agent_conversations/2026-06-09_code_quality_remediation.json
```

Include date, objective, modified files, tests, design decisions, results,
validation, and review resolutions.

Commit:

```text
docs(architecture): document code quality boundaries
```

### Task 7.3: Run Full Quality Gates

```bash
./run.sh uv run ruff check . --fix
./run.sh uv run ruff format .
./run.sh uv run ty check py_modules/sdh_ludusavi/
./run.sh uv run pytest
./run.sh pnpm run test:unit
./run.sh pnpm run typecheck
./run.sh pnpm run build
./run.sh pnpm run verify
./run.sh bash scripts/check_tdd.sh
git diff --check
git status --short
```

If `pnpm verify` fails only because the registry is unreachable, record the
network failure separately from the passing local frontend gates.

### Task 7.4: Run the Code Review Gate

Run:

```bash
codex review --base main
```

The review must verify:

- no behavior or payload changes;
- updater private state is absent from service and main;
- no circular service imports;
- updater persistence is compatible;
- full SHA values cannot be logged;
- Steam runtime access is localized;
- BrowserView native ownership is preserved;
- late async results remain guarded;
- lifecycle fallback polling still starts and stops;
- module budgets represent real responsibility reductions;
- `_run_blocking` is untouched.

Address valid findings in narrow follow-up commits, rerun affected validation,
and repeat review until no blocking finding remains.

## Testing Strategy

Testing follows Red-Green-Refactor for each behavior-changing phase.

### Backend

- Unit-test updater models, parsing, selection, and transport separately.
- Test `PluginUpdater` through state transitions and injected clocks/client.
- Test service integration through facade methods and persisted JSON.
- Test RPC offloading through `main.Plugin`.
- Add AST architecture guards against service coupling and private access.
- Test game-name sanitization directly and through existing call sites.

### Frontend

- Unit-test runtime guards against malformed and missing Steam APIs.
- Unit-test updater controller behavior independently from JSX.
- Unit-test Steam lifecycle event mapping and cleanup independently from
  backup/restore orchestration.
- Unit-test renderer output and BrowserView ownership separately.
- Preserve existing component and integration behavior tests.

### Regression Scenarios

- Cached update result is reused only for matching channel/version within 24
  hours.
- Force check bypasses success cache but respects cooldown.
- Failed check preserves prior successful cache.
- Pending install fast path makes no network request.
- Pending stable version matches stable local metadata but not dev builds.
- Revalidation rejects changed SHA, URL, or version.
- Installer rejection removes optimistic and persisted pending state.
- Missing Steam globals degrade without throwing during render.
- BrowserView fallback method variants retain their receiver.
- Lifecycle fallback polling is cleared on disposal.
- Status surface destroys the native owner only.

## Acceptance Criteria

Implementation is complete when:

- `PluginUpdater` owns updater settings, cache, cooldown, checks, and
  reconciliation;
- `main.py` is only an async adapter for updater operations;
- service updater methods are facade delegations;
- updater modules contain no `service: Any`, service imports, or private service
  access;
- updater persistence remains backward compatible;
- malformed persisted updater values cannot crash startup;
- game-name sanitization has one canonical implementation;
- production Steam runtime access has no scattered inline `as any` casts;
- updater RPC callables are centrally typed;
- large frontend modules are decomposed by responsibility;
- Syncthing tests are split without behavior or coverage loss;
- `_run_blocking` is unchanged;
- all local quality gates pass;
- final review has no blocking findings;
- the branch is committed but not pushed, merged, tagged, or released.

### Baseline Record

- **Branch**: `refactor/code-quality-boundaries`
- **Commit**: `95a7aa3 docs(plan): define phased code quality remediation`
- **Frontend Unit Tests**: 53 passed
- **Backend Tests**: 488 passed
- **Lines of Code**: 22,972 lines (backend + frontend combined source and tests)
