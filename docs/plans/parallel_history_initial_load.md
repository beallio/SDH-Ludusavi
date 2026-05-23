# Plan: Parallel History Initial Load

## Problem Definition
The frontend currently waits for `getSettings()` and then waits for `getGameHistoryCall()` during QAM initial load. These RPCs are independent reads, so the sequential awaits add avoidable startup latency before the panel can continue loading.

## Architecture Overview
Keep the dedicated history RPC and existing state handling unchanged. Only the frontend initial-load orchestration should change so settings and history are fetched in parallel, while versions and command discovery remain in the existing non-blocking background loader.

## Core Data Structures
No data structure changes. `Settings`, `GameOperationHistory`, and `RpcStatus` keep their current shapes.

## Public Interfaces
No public interface changes. `get_settings` and `get_game_history` remain separate RPCs with their current payloads.

## Dependency Requirements
No dependency changes.

## Testing Strategy
Update static frontend coverage to require `Promise.all([getSettings(), getGameHistoryCall()])` inside `loadInitial`, while preserving the existing background versions/command loader. Add backend RPC wiring coverage for `Plugin.get_game_history()`.
