# Plan: Log Environment Variables on Load

The goal is to modify the `pyludusavi` package to log all environment variables when it is loaded. This will help with debugging discovery issues and other environment-related problems.

## Problem Definition
Discovery of Ludusavi often depends on environment variables like `PATH`, `HOME`, `DECKY_USER_HOME`, etc. Currently, these are not logged, making it difficult to diagnose why discovery might fail in certain environments (e.g., when running under Decky Loader).

## Architecture Overview
The logging will be added to the `pyludusavi` package's entry point (`__init__.py`) so that it executes as soon as any part of the package is imported.

## Core Data Structures
- `os.environ`: The dictionary-like object containing environment variables.

## Public Interfaces
- No change to public interfaces, but logs will now contain environment information.

## Dependency Requirements
- `logging`
- `os`

## Testing Strategy
1.  Create a test that imports `pyludusavi` and verifies that the environment variables are logged.
2.  Since logging might already be configured in tests, I'll need to check the captured logs.

## Implementation Steps
1.  Modify `py_modules/pyludusavi/__init__.py`.
2.  Import `os` and `logging`.
3.  Add a logger for the package.
4.  Log `os.environ` at `INFO` level.
5.  Verify with a test.
