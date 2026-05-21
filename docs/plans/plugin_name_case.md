# Plugin Name Case

## Problem Definition

The plugin currently presents itself as `SDH-ludusavi`. The requested display
name is `SDH-Ludusavi`.

## Architecture Overview

The user-facing Decky plugin name is defined in `plugin.json`, the frontend
`definePlugin` metadata, the QAM title, package archive metadata, and visible
README copy. Lowercase package names, Python imports, cache paths, and historical
docs remain unchanged unless they are part of user-facing display text.

## Core Data Structures

- `plugin.json` metadata.
- Frontend plugin registration object.
- Package script constants for archive name/root.
- Static tests that assert package and frontend name contracts.

## Public Interfaces

Decky should display the plugin as `SDH-Ludusavi`. The Python import package
remains `sdh_ludusavi`.

## Dependency Requirements

No dependency changes.

## Testing Strategy

- Update package tests to expect `SDH-Ludusavi` archive metadata.
- Update frontend static tests to expect `SDH-Ludusavi` in the panel title,
  plugin registration, and version label.
- Run focused tests red before implementation, then full validation before
  committing and merging to `main`.
