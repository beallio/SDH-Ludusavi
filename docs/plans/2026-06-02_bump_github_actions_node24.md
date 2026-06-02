Problem Definition
==================

GitHub Actions warns that JavaScript actions targeting Node.js 20 are deprecated. The workflows already run project commands with Node.js 24, but reusable `uses:` actions still declare older action runtime metadata.

Architecture Overview
=====================

All GitHub workflows should opt into Node.js 24 action execution and use currently available newer action major versions where upstream repositories provide them. The change is limited to workflow metadata and static workflow tests.

Core Data Structures
====================

- `.github/workflows/ci.yml`
- `.github/workflows/release.yml`
- `.github/workflows/dev-release.yml`

Public Interfaces
=================

No runtime plugin interfaces change.

Dependency Requirements
=======================

No package dependencies change. Upstream action tags were verified via GitHub tag refs before editing workflows.

Testing Strategy
================

- Extend `tests/test_release_workflows.py` to assert:
  - `FORCE_JAVASCRIPT_ACTIONS_TO_NODE24: true` exists in each workflow.
  - Workflows reference the expected bumped action major versions.
- Run the focused workflow tests before and after implementation.
- Run full local validation and dispatch CI on the branch before merging.
