# Universal Scripting Standards
## Self-Enforcing Agent Protocol

Protocol Version: 2

This document is the project-local operating contract for agents working in this
directory or its subdirectories. Agents must verify the filesystem and dependency state
before making changes, must keep generated caches outside Dropbox, and must use the
project wrapper script for commands that execute project tooling.

---

# 1. Session Initialization

Before implementation work, output this handshake after read-only verification with
`pwd`, `ls`, `git status`, and dependency/config inspection:

```
AGENT_PROTOCOL_HANDSHAKE

Project Root:
Detected Language(s):
Execution Mode: (Script | Project)
Git Repository Present: (Yes/No)
Cache Root: /tmp/{project_dir}
Protocol Version:
Command Wrapper: ./run.sh

Confirmed Policies:
[ ] Top-down planning
[ ] Bottom-up TDD
[ ] Cache isolation
[ ] Verified filesystem state
[ ] Verified dependency state
[ ] Verified run wrapper

STATUS: READY
```

If any field cannot be confirmed, pause and resolve it before implementation.

---

# 2. Project Root Enforcement

By default, generated projects are created next to the `project_template` directory.
Projects may also be created in a custom parent directory when the bootstrap is invoked
with an explicit `--parent-dir <path>` option.

Agents must verify the root with filesystem inspection. Never reference files that have
not been confirmed through filesystem inspection.

---

# 3. Execution Mode Detection

Agents must classify the task as Script Mode or Project Mode.

## Script Mode

Use for a single-file utility with minimal dependencies and no reusable modules.

Characteristics:

```
PEP 723 script metadata
uv run script.py
no pyproject.toml required
```

## Project Mode

Use for reusable modules, multiple files, automated tests, or packaging.

Characteristics:

```
pyproject.toml
uv.lock
src/{package}/
tests/
uv dependency management
```

A repository with `pyproject.toml`, `uv.lock`, `src/`, and `tests/` is Project Mode.

---

# 4. Expected Project Structure

Generated projects use this structure:

```
AGENTS.md
.protocol
.envrc
.python-version
pyproject.toml
uv.lock
run.sh
src/{package}/
tests/
scripts/check_tdd.sh
docs/plans/
docs/specs/
docs/review/
docs/agent_conversations/
.github/workflows/
```

Directory purposes:

- `src/{package}/`: importable project code.
- `tests/`: automated tests.
- `scripts/`: local enforcement and maintenance scripts.
- `docs/plans/`: implementation plans created before code changes.
- `docs/specs/`: durable behavior or interface specifications.
- `docs/review/`: review notes and findings.
- `docs/agent_conversations/`: session summaries.
- `.github/workflows/`: CI workflow definitions when present.

`AGENTS.md` is the only generated agent instruction file. Do not create
Gemini-specific instruction or ignore files.

---

# 5. Command and Cache Policy

Temp files, virtual environments, and tool caches must live under:

```
/tmp/{project_dir}/
```

The virtual environment must be:

```
/tmp/{project_dir}/.venv
```

Run project commands through the wrapper so environment variables are applied:

```
./run.sh <command>
```

The wrapper exports:

```
UV_PROJECT_ENVIRONMENT=/tmp/{project_dir}/.venv
XDG_CACHE_HOME=/tmp/{project_dir}/.cache
PYTHONPYCACHEPREFIX=/tmp/{project_dir}/__pycache__
TMPDIR=/tmp/{project_dir}
```

Required tool cache redirections:

```
uv -> /tmp/{project_dir}/.uv_cache
ruff -> /tmp/{project_dir}/.ruff_cache
pytest -> /tmp/{project_dir}/.pytest_cache
coverage -> /tmp/{project_dir}/.coverage
```

No generated caches may exist inside the repository.

---

# 6. Python Environment Policy

Python projects must use `uv`.

Allowed commands:

```
uv init
uv add
uv sync
uv run
```

For existing projects, run them through the wrapper:

```
./run.sh uv sync
./run.sh uv run pytest
```

Do not use `pip install` or `python -m venv` unless explicitly required. If a virtual
environment is unavoidable, it must be created under `/tmp/{project_dir}/.venv`.

---

# 7. Agent Execution Protocol

Mandatory lifecycle:

```
ANALYZE
PLAN
TEST (RED)
IMPLEMENT (GREEN)
REFACTOR
VALIDATE
COMMIT
DOCUMENT
```

Requirements:

- Planning documents live in `docs/plans/`.
- Tests must exist before implementation.
- Caches and virtual environments must be redirected to `/tmp/{project_dir}`.
- Commits must follow the Conventional Commits specification.
- Pre-commit hooks must run before commits.

For review-only tasks that do not modify files, agents may stop after ANALYZE and
DOCUMENT the findings in the response.

---

# 8. Planning Requirement

Before writing implementation code, create or update:

```
docs/plans/{feature_name}.md
```

The plan must include:

```
Problem Definition
Architecture Overview
Core Data Structures
Public Interfaces
Dependency Requirements
Testing Strategy
```

---

# 9. Strict TDD Enforcement

Agents must follow Red-Green-Refactor.

## Red

Write a failing test describing desired behavior:

```
tests/test_<feature>.py
```

Verify failure:

```
./run.sh uv run pytest
```

## Green

Implement the minimal code required to pass the test.

## Refactor

Improve structure while maintaining passing tests.

## Enforcement Rule

If an agent creates implementation code in the current session without a corresponding
failing test created earlier in the same session, that agent's implementation is invalid.
Do not roll back unrelated user work; add missing tests or ask for direction if existing
changes make compliance impossible.

---

# 10. Git Enforcement

If a repository does not exist:

```
git init -b main
```

The bootstrap script may create the initial scaffold commit on `main`. Subsequent work
must occur in feature branches:

```
feat/<feature>
fix/<bug>
refactor/<component>
docs/<topic>
```

Commits must use Conventional Commits:

```
feat(dataset): add validation layer
fix(driver): initialize selenium service
refactor(logging): simplify handler setup
docs(protocol): update agent bootstrap contract
```

## Atomic Commit Policy

Prefer small, atomic commits that each contain one coherent behavior change, fix,
refactor, or documentation update. Small commits run pre-commit checks sooner and make
failures cheaper to diagnose.

Before starting a new unrelated change, commit the passing current change. Do not batch
large unrelated edits into a single commit unless the user explicitly requests it or the
changes cannot be separated safely.

## Mandatory `.gitignore`

If `.gitignore` does not exist, create one including:

```
__pycache__/
**/__pycache__/
*.pyc
.ruff_cache/
.pytest_cache/
.cache/
.venv/
.venv
dist/
build/
coverage.xml
.coverage
*.parquet
/tmp/
```

Generated artifacts must never be committed.

---

# 11. Dependency and API Verification

Never assume dependencies exist. Verify dependencies through:

```
pyproject.toml
uv.lock
```

If API behavior is uncertain:

1. Read project source or installed package source.
2. Read official documentation.
3. Use web search only when local and official source inspection is insufficient.

Speculative code is forbidden.

---

# 12. Quality Control

Before any commit, agents must execute:

```
./run.sh uv run ruff check . --fix
./run.sh uv run ruff format .
./run.sh uv run ty check src/
./run.sh uv run pytest
```

All checks must pass. The generated pre-commit hook runs the same core checks plus
`scripts/check_tdd.sh`.

---

# 13. Documentation Requirements

Every project must include:

```
README.md
docs/
docs/plans/
docs/specs/
docs/review/
docs/agent_conversations/
```

README must contain:

```
project description
installation instructions
usage examples
dependency requirements
```

When creating a new release tag for a GitHub project, increment the `cacheBuster`
parameter in README image URLs so images refresh immediately.

---

# 14. Agent Session Logging

For implementation tasks, record a session summary in:

```
docs/agent_conversations/
```

Each session log must include:

```
date
task objective
files modified
tests added
design decisions
results
```

Example file:

```
docs/agent_conversations/2026-05-07_update_agent_protocol.json
```

---

# 15. Definition of Done

A modifying task is complete only if:

```
[ ] ruff check passed
[ ] ruff format applied
[ ] ty check passed
[ ] tests pass via ./run.sh uv run pytest
[ ] README updated when behavior or usage changed
[ ] dependencies documented when dependencies changed
[ ] caches redirected to /tmp
[ ] session log recorded
```

---

# 16. Failure Recovery Protocol

If execution fails:

1. Capture the error output.
2. Identify the failing component.
3. Write or update a reproduction test.
4. Fix the root cause.
5. Re-run the validation suite.

Blind retries are forbidden.

---

# 17. Required Confirmation

After reviewing this file, confirm:

- Temp files and caches are under `/tmp/{project_dir}`.
- The shell wrapper to run before project commands is `./run.sh`.
- `ty` is the official type checker.
