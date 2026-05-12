# Plan - Improve Non-Steam Game Matching with Aliases

Enhance the game name matching logic to handle non-Steam games by incorporating Ludusavi's alias and custom game systems, and implementing fuzzy matching.

## Problem Definition
1. **Non-Steam Game Hooks Failing:** Game start/exit hooks aren't working for non-Steam games, likely due to naming mismatches between Steam and Ludusavi.
2. **Missing Alias Support:** SDH-ludusavi doesn't currently check Ludusavi's `customGames` for aliases, which are commonly used to map friendly Steam names to canonical Ludusavi entries.
3. **Conservative Normalization:** Current name normalization is too aggressive, potentially losing useful distinguishing characters.

## Proposed Solution

### 1. Alias-Aware Data Collection
- **Update Backend Adapter:** Modify `PyludusaviAdapter` to extract aliases from Ludusavi's configuration using `pyludusavi.config_show()`.
- **Alias Map:** Build a mapping of `custom_name -> canonical_name` to resolve non-Steam game names.

### 2. Robust Matching Strategy
- **Alias Resolution:** When a hook is triggered, first check if the provided name matches a known alias.
- **Normalization Fallback:** Use a refined `_normalize` function that retains more characters (e.g., periods, hyphens) for better precision.
- **Fuzzy/Substring Matching:** If no exact match is found, check if the Steam name is a significant substring of a Ludusavi name (or vice-versa).

### 3. Improved Diagnostics
- **Log Unmatched Hooks:** Log full details (`game_name`, `app_id`, `normalized_name`) at `info` level when a match fails.
- **Matching Trace:** Log the specific reason for a successful match (e.g., "Matched via exact name", "Matched via alias", "Matched via substring").

## Changes

### Backend (`py_modules/sdh_ludusavi/service.py`)
- Refactor `_match_game` to:
    - Resolve aliases before matching.
    - Implement substring/fuzzy fallback matching.
    - Log raw and normalized names during matching attempts.
- Update `_normalize` to be less aggressive.
- Change `handle_game_start/exit` logs from `debug` to `info` for unmatched scenarios.

### Backend (`py_modules/sdh_ludusavi/ludusavi.py`)
- Update `PyludusaviAdapter.refresh_statuses` to also return a dictionary of aliases.

## Verification & Testing
1. **Alias Matching Test:** Add a test case to `tests/test_service.py` that verifies a game can be matched using an alias.
2. **Fuzzy Matching Test:** Add a test case for near-miss names (e.g., "The Witcher 3" vs "The Witcher 3: Wild Hunt").
3. **Log Check:** Ensure logs clearly show why a game was (or wasn't) matched.
