# Contributing to EQUIPA

## Table of Contents

- [Contributing to EQUIPA](#contributing-to-equipa)
  - [Welcome](#welcome)
  - [Development Setup](#development-setup)
- [Clone the repo](#clone-the-repo)
- [Make sure you have Python 3.10+](#make-sure-you-have-python-310)
- [Set up the database](#set-up-the-database)
- [Verify everything works](#verify-everything-works)
    - [Database Migrations](#database-migrations)
- [Run migrations](#run-migrations)
- [Benchmark migrations (optional, but nice to verify)](#benchmark-migrations-optional-but-nice-to-verify)
  - [Code Style](#code-style)
    - [The Rules](#the-rules)
    - [Conventions](#conventions)
    - [File Organization](#file-organization)
  - [Making Changes](#making-changes)
    - [Branch Naming](#branch-naming)
    - [Commit Messages](#commit-messages)
    - [What to Keep in Mind](#what-to-keep-in-mind)
  - [Testing](#testing)
- [Run the full suite](#run-the-full-suite)
- [Run a specific test file](#run-a-specific-test-file)
- [Run a specific test](#run-a-specific-test)
- [Some tests also have their own main() runners](#some-tests-also-have-their-own-main-runners)
    - [What to Test](#what-to-test)
    - [Writing Tests](#writing-tests)
  - [Pull Request Process](#pull-request-process)
    - [Before You Open a PR](#before-you-open-a-pr)
    - [PR Description](#pr-description)
    - [Review Expectations](#review-expectations)
    - [Things That Will Get Your PR Stuck](#things-that-will-get-your-pr-stuck)
  - [Issue Reporting](#issue-reporting)
    - [Bugs](#bugs)
    - [Feature Requests](#feature-requests)
    - [Known Issues You Don't Need to Report](#known-issues-you-dont-need-to-report)
  - [Code of Conduct](#code-of-conduct)
  - [Related Documentation](#related-documentation)

## Welcome

Hey, thanks for checking this out. EQUIPA is a multi-agent AI orchestrator — you talk to Claude in plain English, and it dispatches AI agents to build, test, review, and secure your code. The whole thing is pure Python stdlib with zero dependencies, and we'd like to keep it that way.

Whether you're fixing a typo, squashing a bug, or adding a new agent role, we're glad you're here. This doc covers how to get set up and how we work together.

---

## Development Setup

EQUIPA has zero pip dependencies. That's intentional. The entire project runs on Python's standard library plus SQLite. Setting up is fast.

```bash
# Clone the repo
git clone https://github.com/your-org/equipa.git
cd equipa

# Make sure you have Python 3.10+
python3 --version

# Set up the database
python3 equipa_setup.py

# Verify everything works
python3 -m pytest tests/ -v
```

That's it. No virtual environment dance, no `pip install -r requirements.txt`, no Docker compose files. If you have Python 3.10+ and SQLite, you're good.

**A note on how people actually use EQUIPA:** Most users don't interact with the CLI directly. They talk to Claude (the AI assistant), and Claude runs EQUIPA behind the scenes — dispatching tasks, monitoring agents, reporting results. If you're contributing, you'll use the CLI and tests directly, but keep in mind that the conversational interface is the primary way people experience this project.

### Database Migrations

If you're working on schema changes:

```bash
# Run migrations
python3 db_migrate.py

# Benchmark migrations (optional, but nice to verify)
python3 tools/benchmark_migrations.py
```

---

## Code Style

### The Rules

- **Pure Python stdlib.** No external dependencies. This is non-negotiable. If you need something that isn't in the standard library, implement it yourself or find another way. The zero-dependency constraint is a core design decision, not laziness.
- **No type-checking libraries.** We use type hints for documentation, but we don't enforce them with mypy or similar tools.
- **SQLite for everything.** The database is the source of truth. 30+ tables. Learn the schema before making changes.

### Conventions

- Functions over classes, unless state management genuinely requires a class
- Snake_case for everything (functions, variables, files)
- Docstrings for public functions — keep them short and honest
- Keep files focused. If a module is doing three different things, split it up
- Comments should explain *why*, not *what*. The code already says what it does

### File Organization

```
equipa/           # Core package — orchestration, dispatch, routing, etc.
skills/           # Agent skill definitions and resources
tests/            # All tests live here
tools/            # Dashboards, benchmarks, arena, training data prep
forgesmith*.py    # Self-improvement system (ForgeSmith, GEPA, SIMBA)
```

---

## Making Changes

### Branch Naming

Keep it simple and descriptive:

- `fix/loop-detection-false-positive`
- `feature/ollama-model-routing`
- `docs/update-contributing`
- `test/add-mcp-health-coverage`

### Commit Messages

Write commit messages like you're explaining the change to someone who'll read it six months from now.

```
fix: early termination killing agents on legitimate complex tasks

The 10-turn read threshold was too aggressive for tasks that need
to understand large codebases before making changes. Bumped exempt
roles and added complexity-aware thresholds.
```

Format: `type: short description` on the first line. Types: `fix`, `feature`, `test`, `docs`, `refactor`, `perf`.

Body is optional but appreciated for anything non-trivial.

### What to Keep in Mind

- **Zero dependencies.** Seriously. Don't add any.
- **The conversational model matters.** Users talk to Claude, Claude runs EQUIPA. If your change affects how tasks are created, dispatched, or reported, think about how that flows through a conversation.
- **Agents are the users of your code.** A lot of this codebase is consumed by AI agents, not humans. Prompts, tool definitions, output parsing — these need to be clear and unambiguous because agents take things literally.

---

## Testing

EQUIPA has 334+ tests. Run them before opening a PR.

```bash
# Run the full suite
python3 -m pytest tests/ -v

# Run a specific test file
python3 -m pytest tests/test_early_termination.py -v

# Run a specific test
python3 -m pytest tests/test_loop_detection.py::test_warning_at_threshold -v

# Some tests also have their own main() runners
python3 tests/test_early_termination.py
python3 tests/test_lesson_sanitizer.py
python3 tests/test_agent_messages.py
```

### What to Test

- **If you change agent behavior** — test the dispatch, routing, and output parsing
- **If you change the database schema** — add migration tests (see `tests/test_db_migration_v5.py` for examples)
- **If you touch ForgeSmith/GEPA/SIMBA** — test the self-improvement pipeline (see `tests/test_forgesmith_simba.py`)
- **If you change cost routing** — the circuit breaker and complexity scoring have dedicated tests in `tests/test_cost_routing.py`
- **If you modify early termination** — this is a big one. Lots of edge cases. See `tests/test_early_termination.py` — it's thorough for a reason
- **If you add a new feature flag** — add it to `tests/test_feature_flags.py`

### Writing Tests

- Use `pytest` conventions — `test_` prefix, fixtures where they help
- Use `tmp_path` and `monkeypatch` from pytest for isolation. Don't leave test databases lying around
- Test the failure cases too, not just the happy path. Agents fail a lot. That's normal.
- Keep tests readable. A test name like `test_circuit_breaker_degrades_after_5_failures` tells you everything

---

## Pull Request Process

### Before You Open a PR

1. Run the full test suite. All 334+ tests should pass
2. If you added new functionality, add tests for it
3. If you changed prompts or agent behavior, verify it actually works by dispatching a test task (if you can)
4. Make sure you haven't accidentally added an external dependency

### PR Description

Tell us:

- **What** you changed
- **Why** you changed it
- **How** to verify it works
- Any **known limitations** of your approach (be honest — we'd rather know upfront)

### Review Expectations

- Someone will review your PR. We'll try to be quick but no promises on timeline
- We'll check for: test coverage, zero-dependency compliance, code clarity, and whether the change makes sense for the conversational usage model
- Don't take feedback personally. We're all trying to make agents less dumb
- Small PRs get reviewed faster than big ones. If your change is huge, consider splitting it up

### Things That Will Get Your PR Stuck

- Adding pip dependencies
- Breaking existing tests
- Changing database schema without a migration
- Modifying agent prompts without testing them against real tasks
- PRs with no tests for new functionality

---

## Issue Reporting

### Bugs

When filing a bug, include:

- What you expected to happen
- What actually happened
- Steps to reproduce (be specific — "it doesn't work" doesn't help)
- Python version and OS
- Relevant log output (agent logs live in the logs directory)
- If it's an agent behavior issue: which role, what task type, and roughly how many turns it took before things went sideways

### Feature Requests

We're open to ideas. Tell us:

- What problem you're trying to solve
- How you imagine the solution working
- Whether you're willing to implement it yourself (no pressure either way)

### Known Issues You Don't Need to Report

These are things we already know about:

- **Agents get stuck on complex tasks.** Analysis paralysis is real. They'll read the same files over and over instead of making changes. We're working on it.
- **Git worktree merges occasionally need manual intervention.** The isolation model is still being refined.
- **Self-improvement (ForgeSmith/GEPA/SIMBA) needs 20-30 tasks before patterns emerge.** It's not magic on day one.
- **The Tester role depends on your project having a working test suite.** If your tests are broken to begin with, the Tester can't help.
- **Early termination kills agents at 10 turns of reading.** Some legitimate complex tasks actually need more. This is a tuning problem we're actively working on.

If you hit one of these, you can still file an issue — especially if you have ideas for fixing it — but know that we're aware.

---

## Code of Conduct

Be kind. Be patient. Assume good intent.

We're building tools that help developers get more done. That works best when everyone feels welcome contributing, asking questions, and making mistakes.

- Treat others with respect, regardless of experience level
- Give constructive feedback, not dismissive feedback
- No harassment, no discrimination, no being a jerk
- If someone's being a jerk, let the maintainers know

This project is named after the Portuguese word for "team." Let's act like one.
---

## Related Documentation

- [Readme](README.md)
- [Architecture](ARCHITECTURE.md)
- [Api](API.md)
- [Deployment](DEPLOYMENT.md)
