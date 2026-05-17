# Remaining Cache Review Suggestions

This note captures the review suggestions that were not fully implemented in
`0bd7370 refactor(cache): invalidate on Ludusavi config changes`.

## Already Addressed

- The cache now invalidates when Ludusavi's active config file `st_mtime_ns` changes.
- The scope is explicitly SteamOS Game Mode and Steam-visible games or shortcuts.
- External backup-status changes are intentionally not cache invalidators because backup
  and restore paths validate live Ludusavi state before acting.
- Pending cache markers are cleared on refresh failure.

## Addressed: Normalize Installed App IDs

Implemented in the review-response commit: the service no longer persists the raw
`installed_app_ids` string received over the frontend RPC boundary.

Recommended behavior:

- Parse the optional marker in `SDHLudusaviService.refresh_games` before comparison or
  persistence. Implemented.
- Accept only unsigned integer IDs.
- Deduplicate and sort IDs in the backend even though the frontend already sorts them.
- Reject or ignore oversized input before it can bloat `state.json`.

One simple representation:

```python
def _normalize_installed_app_ids(raw: str | None) -> str | None:
    if raw is None:
        return None
    if len(raw) > MAX_INSTALLED_APP_IDS_BYTES:
        return None
    ids = sorted({int(token) for token in raw.split(",") if token.isdecimal()})
    return ",".join(str(app_id) for app_id in ids)
```

Optional future refinement: store a hash of the normalized string for an even more
compact state file:

```python
hashlib.sha256(normalized.encode("ascii")).hexdigest()
```

Suggested tests:

- Duplicate IDs normalize to the same marker as unique IDs. Implemented.
- Unsorted IDs normalize to the same marker as sorted IDs. Implemented.
- Non-numeric tokens are rejected. Implemented.
- Oversized input is ignored and does not get persisted. Implemented.
- Existing cache behavior still invalidates when the normalized marker changes. Covered
  by the existing app-ID invalidation test.

## Optional Frontend Contract Test

The backend tests now cover the config marker behavior. A future static frontend test
could still document that `refreshGamesCall` sends only Steam app membership and that
Ludusavi config validation is backend-owned.

This is documentation-level coverage rather than a functional gap.
