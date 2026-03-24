# Contributing to EQUIPA

## Table of Contents

- [Contributing to EQUIPA](#contributing-to-equipa)
  - [Development Setup](#development-setup)
    - [Prerequisites](#prerequisites)
    - [Local Setup](#local-setup)
    - [Project Structure](#project-structure)
  - [Code Style](#code-style)
    - [Security Conventions](#security-conventions)
  - [Making Changes](#making-changes)
    - [Branch Naming](#branch-naming)
    - [Commit Messages](#commit-messages)
    - [Development Workflow](#development-workflow)
  - [Testing](#testing)
    - [Running All Tests](#running-all-tests)
    - [Running Specific Test Files](#running-specific-test-files)
- [Early termination logic](#early-termination-logic)
- [Loop detection](#loop-detection)
- [Agent message passing](#agent-message-passing)
- [Forgesmith SIMBA rules](#forgesmith-simba-rules)
- [Rubric quality scoring](#rubric-quality-scoring)
- [Lesson sanitizer](#lesson-sanitizer)
- [Episode injection](#episode-injection)
    - [Running Benchmarks](#running-benchmarks)
    - [What to Test](#what-to-test)
    - [Test Conventions](#test-conventions)
  - [Pull Request Process](#pull-request-process)
    - [Before Submitting](#before-submitting)
    - [PR Description Template](#pr-description-template)
  - [What](#what)
  - [Why](#why)
  - [How](#how)
  - [Testing](#testing)
  - [Risk](#risk)
    - [Review Expectations](#review-expectations)
  - [Issue Reporting](#issue-reporting)
    - [Bug Reports](#bug-reports)
    - [Feature Requests](#feature-requests)
    - [Security Issues](#security-issues)
  - [Code of Conduct](#code-of-conduct)
  - [Related Documentation](#related-documentation)

Welcome! We're glad you're interested in contributing to EQUIPA — a multi-agent AI orchestration platform built in pure Python. Whether you're fixing a bug, adding a feature, improving documentation, or writing tests, your contribution matters. This project thrives on collaboration, and we want to make the process as smooth as possible.

## Development Setup

EQUIPA is built with **pure Python stdlib** and has **zero pip dependencies**, so getting started is straightforward.

### Prerequisites

- Python 3.10+
- SQLite3
- Git
- (Optional) An Ollama instance for local model testing
- (Optional) Anthropic API access for Claude-based features

### Local Setup

1. **Clone the repository:**
   ```bash
   git clone https://github.com/your-org/Equipa-repo.git
   cd Equipa-repo
   ```

2. **Run the interactive setup:**
   ```bash
   python equipa_setup.py
   ```
   This will walk you through database initialization, configuration generation, and optional component setup (Sentinel, ForgeBot).

3. **Initialize the database manually (if needed):**
   ```bash
   python db_migrate.py
   ```
   This runs all migrations and brings your schema to the latest version (v4+).

4. **Verify the installation:**
   ```bash
   python -c "from equipa.db import get_db_connection; print('DB OK')"
   python -m pytest tests/ -v
   ```

### Project Structure

```
equipa/              # Core library — CLI, dispatch, parsing, monitoring, etc.
tests/               # Test suite
tools/               # Utilities — dashboard, arena, benchmarks, training data
skills/              # Agent skill definitions (SARIF parsing, etc.)
forgesmith*.py       # Self-improvement subsystems (GEPA, SIMBA, impact analysis)
autoresearch_*.py    # Automated prompt optimization loops
```

## Code Style

EQUIPA follows a pragmatic, readable Python style. There are no external linters configured, but please adhere to these conventions:

- **PEP 8** for general formatting — 4-space indentation, snake_case for functions and variables.
- **No external dependencies.** This is a core project principle. Everything runs on Python stdlib. If you need something from PyPI, open an issue to discuss it first.
- **Functions over classes** where possible. The codebase favors standalone functions with clear inputs/outputs. Classes are used sparingly (e.g., `LoopDetector`, `Finding`).
- **Docstrings** aren't required on every function, but complex logic should have a comment explaining *why*, not just *what*.
- **SQL in Python files** is fine — the project uses inline SQL with SQLite extensively. Use parameterized queries (`?` placeholders) to prevent injection.
- **Keep imports stdlib-only.** Group them: stdlib first, then local project imports.

### Security Conventions

Given the project's nature (executing agent-generated code), security is taken seriously:

- Use `safe_path()` to validate any file paths derived from user/agent input.
- Use `is_blocked_command()` and `is_safe_read_command()` when handling shell execution.
- Use `wrap_untrusted()` from `equipa/security.py` for untrusted content.
- Sanitize lessons and error signatures through `lesson_sanitizer.py` before storage.

## Making Changes

### Branch Naming

Use descriptive branch names with a prefix:

- `feat/` — new features (e.g., `feat/ollama-model-routing`)
- `fix/` — bug fixes (e.g., `fix/loop-detection-false-positive`)
- `docs/` — documentation changes
- `test/` — new or improved tests
- `refactor/` — code cleanup without behavior change

### Commit Messages

Write clear, concise commit messages:

```
<type>: <short summary>

<optional longer description>
```

**Examples:**
```
fix: prevent monologue detection from firing during first 5 turns
feat: add cost breaker termination for runaway agents
test: add coverage for alternating tool loop patterns
docs: update CLAUDE.md with new forgesmith_impact module
```

### Development Workflow

1. Create a branch from `main`.
2. Make your changes in small, logical commits.
3. Run the test suite before pushing (see Testing below).
4. Open a pull request with a clear description of what changed and why.

## Testing

The project has an extensive test suite in `tests/`. Tests are written using both `pytest` and standalone test runners.

### Running All Tests

```bash
python -m pytest tests/ -v
```

### Running Specific Test Files

```bash
# Early termination logic
python -m pytest tests/test_early_termination.py -v

# Loop detection
python -m pytest tests/test_loop_detection.py -v

# Agent message passing
python -m pytest tests/test_agent_messages.py -v

# Forgesmith SIMBA rules
python -m pytest tests/test_forgesmith_simba.py -v

# Rubric quality scoring
python tests/test_rubric_quality_scorer.py

# Lesson sanitizer
python tests/test_lesson_sanitizer.py

# Episode injection
python tests/test_episode_injection.py
```

### Running Benchmarks

```bash
python tools/benchmark_migrations.py
```

### What to Test

- **New functions** should have corresponding tests in `tests/`.
- **Bug fixes** should include a regression test that would have caught the bug.
- **Security-sensitive changes** (command execution, file path handling, lesson injection) must have tests verifying the safety boundaries.
- **Database schema changes** need migration tests — see `tools/benchmark_migrations.py` for the pattern.

### Test Conventions

- Some test files use `pytest` fixtures and `conftest.py`; others use standalone `main()` / `run_all_tests()` runners. Follow the pattern of the file you're modifying.
- Tests that need a database should create a temporary one (see `make_temp_db()` in `test_agent_messages.py`).
- Use `monkeypatch` for mocking external calls (Ollama, Claude API, subprocess).
- The `conftest.py` handles test ordering and configuration — don't bypass it.

## Pull Request Process

### Before Submitting

- [ ] All existing tests pass (`python -m pytest tests/ -v`)
- [ ] New code has test coverage
- [ ] No new external dependencies introduced
- [ ] Security-sensitive paths use existing safety functions
- [ ] Commit messages are clear and descriptive

### PR Description Template

```markdown
## What

Brief description of what this PR does.

## Why

The problem this solves or the feature this enables.

## How

Key implementation details, if non-obvious.

## Testing

How you verified this works. Which tests were added or modified.

## Risk

What could break? Does this affect agent dispatch, prompt generation, 
or database schema?
```

### Review Expectations

- PRs will be reviewed for correctness, security implications, and adherence to the zero-dependency principle.
- Schema changes require a migration in `db_migrate.py` and must be backward-compatible.
- Changes to prompt files or Forgesmith logic may need extra scrutiny since they affect agent behavior at scale.
- Expect constructive feedback — we optimize for a reliable, secure system.

## Issue Reporting

### Bug Reports

Open an issue with:

- **Title:** Clear, specific summary of the problem.
- **Environment:** Python version, OS, SQLite version.
- **Steps to reproduce:** What you did, what you expected, what happened instead.
- **Logs/output:** Relevant error messages, stack traces, or agent logs.
- **Database state:** If relevant, which tables/rows are involved (don't share sensitive data).

### Feature Requests

Open an issue with:

- **Title:** What you'd like to see.
- **Use case:** Why this would be useful — what workflow does it improve?
- **Proposed approach:** If you have ideas on implementation, share them. Include which modules would be affected.
- **Constraints:** Remember the zero-dependency and pure-stdlib principles.

### Security Issues

If you discover a security vulnerability (especially around command execution, path traversal, or prompt injection), **please report it privately** rather than opening a public issue. Contact the maintainers directly.

## Code of Conduct

We are committed to providing a welcoming, inclusive, and harassment-free experience for everyone. All contributors are expected to:

- Be respectful and constructive in all interactions.
- Welcome newcomers and help them get oriented.
- Focus feedback on the code, not the person.
- Assume good intent, and clarify before escalating.

We have zero tolerance for harassment, discrimination, or hostile behavior of any kind. Maintainers reserve the right to remove content or ban contributors who violate these principles.

---

Thank you for contributing to EQUIPA. Every improvement — whether it's a one-line fix or a new subsystem — helps make multi-agent orchestration more reliable for everyone. 🚀
---

## Related Documentation

- [Architecture](ARCHITECTURE.md)
- [Api](API.md)
- [Deployment](DEPLOYMENT.md)
