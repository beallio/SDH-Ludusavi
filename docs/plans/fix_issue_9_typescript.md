# Plan - Fix Issue 9: TypeScript Validation and Missing Dependencies

## Problem Definition
TypeScript validation fails due to conflicting global declarations and missing `react-router` types.

## Architecture Overview
- Simplify `src/types/steam-globals.d.ts` to avoid conflicts with `@decky/ui`.
- Add `react-router` to `package.json`.
- Use a safe helper to access `SteamClient` with runtime guards.

## Core Data Structures
N/A

## Public Interfaces
N/A

## Dependency Requirements
- `react-router` (npm)

## Testing Strategy
- Run `./node_modules/.bin/tsc --noEmit` and ensure it passes.

## Task List
1. Create branch `fix/issue-9-typescript`.
2. Verify TSC failure.
3. Add `react-router` to `package.json` and install.
4. Simplify `src/types/steam-globals.d.ts`.
5. Update `src/index.tsx` to use safe `SteamClient` access if needed.
6. Verify TSC passes.
7. Commit.
