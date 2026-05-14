# Plan: Merge and Cleanup

## Problem Definition
The current feature development and maintenance work on `chore-npm-supply-chain-hardening` is complete. There are several other feature branches that should be merged or cleaned up if they are already integrated into the current state or are no longer needed.

## Strategy
1.  Verify that the current branch `chore-npm-supply-chain-hardening` passes all tests and quality checks.
2.  Switch to `main`.
3.  Merge `chore-npm-supply-chain-hardening` into `main`.
4.  Identify which other branches (`feat-sdh-ludusavi`, `feat-sdh-ludusavi-version`, `feat/limit-installed-games`, `feat/ludusavi-logs-and-version`, `feat/ui-refinement`) are already merged into `main` or the merged branch.
5.  Delete the merged branches.

## Testing Strategy
1.  Run the full validation suite (ruff, ty, pytest, pnpm audit, etc.) on `main` after the merge.
2.  Verify `git branch --merged main` to confirm branches are safe to delete.

## Steps
1.  Run quality checks on `chore-npm-supply-chain-hardening`.
2.  `git checkout main`
3.  `git merge chore-npm-supply-chain-hardening`
4.  `git branch --merged main`
5.  `git branch -d <merged_branches>`
