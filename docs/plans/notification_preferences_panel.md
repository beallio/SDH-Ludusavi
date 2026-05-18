# Notification Preferences Panel

## Problem Definition

Users need one place to control SDH-ludusavi Decky toast notifications. They must be
able to disable all notifications, disable categories independently, and see granular
controls become unavailable when the global notification toggle is off.

## Architecture Overview

Notification preferences are plugin settings, so the backend owns persistence in the
existing state file and the frontend owns toast gating. The lifecycle handlers live
outside React component state, so the frontend also keeps a module-level mirror of the
notification settings alongside the existing auto-sync notification mirror.

## Core Data Structures

- `notifications.enabled`
- `notifications.auto_sync_progress`
- `notifications.auto_sync_results`
- `notifications.manual_operations`
- `notifications.refresh_status`
- `notifications.failures_errors`

Missing or malformed legacy state defaults every notification category to enabled.

## Public Interfaces

- Extend `Settings` with a `notifications` object.
- Add backend/frontend RPC `set_notification_settings(settings) -> Settings`.
- Route every Decky toast through one notification-aware frontend helper.

## Dependency Requirements

No dependency changes are required.

## Testing Strategy

- Backend tests for default settings, persistence, legacy migration, and malformed
  notification setting coercion.
- Frontend static tests for the Notifications panel, disabled granular controls, RPC
  wiring, module-level mirror updates, and centralized toast categories.
- Validate with targeted tests, frontend typecheck, and the full repo validation suite.
