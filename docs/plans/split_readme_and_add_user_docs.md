# Plan: Split README into User and Developer Documentation

Separate user-facing instructions from technical development documentation to improve clarity for potential early adopters.

## Problem Definition
The current `README.md` commingles installation/usage instructions with technical architecture, build steps, and internal state details. This is confusing for users who just want to install the plugin and set up their save sync workflow. Additionally, because the plugin is not yet in the Decky Store or on GitHub, users need specific instructions on how to install it via Developer Mode.

## Proposed Changes

### 1. `README.md` (User Guide)
- **Introduction**: Brief overview of the plugin.
- **Installation**:
  - How to enable Decky Loader Developer Mode (required for early-access installation).
  - Instructions for installing via "Install from URL" (placeholder) or "Install from ZIP".
- **Prerequisites**:
  - Ludusavi Flatpak installation.
- **Recommended Workflow (The "Gold Standard")**:
  - Setting up **SyncThingy** Flatpak.
  - Setting up the **Syncthing Decky Plugin**.
  - Configuring Ludusavi to backup to a Syncthing-watched folder (e.g., `$HOME/ludusavi-backup`).
  - **Important Warning**: The requirement for an online node for synchronization.
- **Ludusavi Resources**:
  - Links to Backup Retention and Cloud Backup docs.
  - Warning about cloud backup lag/offline failure.
- **Simplified Status Guide**:
  - Explain common UI labels like "Backup ready" and "Needs first backup".

### 2. `DEVELOPMENT.md` (Technical Reference)
- **Build Instructions**: `uv`, `pnpm`, and `run.sh` usage.
- **Project Architecture**: Backend/frontend split, vendored modules.
- **State & Runtime**: Details on `SettingsManager` and cache locations.
- **Exhaustive Status Reference**: Full list of RPC status codes, skip reasons, and internal operation states.
- **Validation**: Quality control steps and pre-commit hooks.

### 3. `AGENTS.md`
- Update section #4 (Expected Project Structure) and #13 (Documentation Requirements) to include `DEVELOPMENT.md`.

## Implementation Steps

### [DOCS]
1. Create `docs/plans/split_readme_and_add_user_docs.md` (this plan).
2. Create `DEVELOPMENT.md` by migrating technical content from the current `README.md`.
3. Rewrite `README.md` with a focus on user installation and the Syncthingy workflow.
4. Update `AGENTS.md` to reference `DEVELOPMENT.md`.

## Verification Plan
1. Manually review both Markdown files for formatting and link correctness.
2. Verify that the user README contains all the specific instructions for SyncThingy and Developer Mode.
3. Verify that `DEVELOPMENT.md` remains a complete technical reference.
