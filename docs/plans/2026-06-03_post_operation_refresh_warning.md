# Plan: Post-Operation Refresh Warning Wording

## Problem Definition
`GameRegistry.refresh_after_operation()` handles refresh failures after both backup and restore operations, but its warning message still says "Post-backup status refresh failed". That wording is misleading after restore operations.

## Architecture Overview
Keep the existing broad exception boundary and logging level/category unchanged. Rename only the user-visible warning text to use operation-neutral language.

## Core Data Structures
No data structure changes.

## Public Interfaces
No API changes.

## Dependency Requirements
No dependency changes.

## Testing Strategy
Update the existing exception-boundary test to assert the neutral "Post-operation status refresh failed" warning while preserving the refresh failure detail.
