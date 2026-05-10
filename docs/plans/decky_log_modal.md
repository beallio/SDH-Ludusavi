# Decky Log Modal Plan

## Problem Definition

Replace the inline plugin log display with a native Decky modal so logs have a
dedicated scrollable reading area.

## Architecture Overview

- Add a standalone `LogModal` component above `Content`.
- Render `LogModal` inside a Decky `ConfirmModal`.
- Open the modal from the existing Show Logs button through Decky's modal API.
- Remove the `showLogs` state and inline log rendering block.

## Core Data Structures

No backend data changes. The modal receives the existing `LogEntry[]` array.

## Public Interfaces

No backend RPC changes.

## Dependency Requirements

Use Decky UI's `ConfirmModal` and the installed Decky modal API. The installed
`@decky/api` package does not export `showModal`, while `@decky/ui` does.

## Testing Strategy

- Add frontend static assertions for the modal component, modal styling, and Show
  Logs button integration.
- Verify the old inline state and conditional rendering are removed.
- Run the local pre-commit hook and frontend build before committing.
