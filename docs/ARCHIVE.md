# Documentation Archive

Historical implementation plans, review artifacts, and session logs are preserved on
the orphan `docs-archive` branch instead of the active development tree.

## Archived Snapshots

- 196 session logs through June 11, 2026 were archived from `dev@341e94b`.
- 220 plans, reviews, and session logs last committed on or before June 11, 2026 were
  archived from `dev@29ca44bc79e9c8e66d840491aadef5b560647a79`.

The second snapshot is committed as `3f83b00` on `docs-archive`.
`ARCHIVE_MANIFEST.txt` on that branch records every archived path and its source Git
blob object ID.

## Retrieve A File

Inspect a historical file without changing branches:

```text
git show docs-archive:docs/<path>
```

List the archived files:

```text
git show docs-archive:ARCHIVE_MANIFEST.txt
```

Check out the archive in a temporary worktree:

```text
git worktree add /tmp/sdh_ludusavi/docs_archive_wt docs-archive
```

Remove the temporary worktree when finished:

```text
git worktree remove /tmp/sdh_ludusavi/docs_archive_wt
git worktree prune
```

Durable specifications, documentation used by tests, and records created after the
June 11 cutoff remain in the active tree.
