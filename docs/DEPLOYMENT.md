# DEPLOYMENT.md — EQUIPA

## Table of Contents

- [DEPLOYMENT.md — EQUIPA](#deploymentmd-equipa)
  - [TL;DR](#tldr)
  - [Prerequisites](#prerequisites)
  - [Step-by-Step Setup](#step-by-step-setup)
    - [1. Clone the repository](#1-clone-the-repository)
    - [2. Run the interactive setup wizard](#2-run-the-interactive-setup-wizard)
    - [3. Run database migrations (if upgrading or starting fresh)](#3-run-database-migrations-if-upgrading-or-starting-fresh)
    - [4. Verify the installation](#4-verify-the-installation)
    - [5. Run your first task](#5-run-your-first-task)
- [Dispatch pending work automatically](#dispatch-pending-work-automatically)
- [Or dispatch a specific task by ID](#or-dispatch-a-specific-task-by-id)
- [Or dispatch by goal file](#or-dispatch-by-goal-file)
  - [Environment Variables](#environment-variables)
  - [Configuration Files](#configuration-files)
    - [Editing dispatch config](#editing-dispatch-config)
- [View current config](#view-current-config)
- [Key sections:](#key-sections)
- [- "roles": defines available agent roles](#-roles-defines-available-agent-roles)
- [- "features": feature flag toggles](#-features-feature-flag-toggles)
- [- "models": provider and model per role](#-models-provider-and-model-per-role)
- [- "max_turns": turn budgets per complexity level](#-max_turns-turn-budgets-per-complexity-level)
  - [Running in Production](#running-in-production)
    - [Option A: Cron-based (recommended for solo/small team)](#option-a-cron-based-recommended-for-solosmall-team)
- [Run Forgesmith optimizer nightly at 2 AM](#run-forgesmith-optimizer-nightly-at-2-am)
- [Forgesmith self-improvement loop](#forgesmith-self-improvement-loop)
- [Nightly review report](#nightly-review-report)
- [Auto-dispatch pending work every 30 minutes](#auto-dispatch-pending-work-every-30-minutes)
    - [Option B: systemd service](#option-b-systemd-service)
- [/etc/systemd/system/equipa-dispatch.service](#etcsystemdsystemequipa-dispatchservice)
- [/etc/systemd/system/equipa-dispatch.timer](#etcsystemdsystemequipa-dispatchtimer)
    - [Option C: PM2 (if you prefer Node-style process management)](#option-c-pm2-if-you-prefer-node-style-process-management)
  - [Docker](#docker)
- [Dockerfile](#dockerfile)
- [No pip install needed — zero dependencies](#no-pip-install-needed-zero-dependencies)
- [Initialize database](#initialize-database)
- [Default: run nightly review (swap for your use case)](#default-run-nightly-review-swap-for-your-use-case)
- [Build](#build)
- [Run nightly review](#run-nightly-review)
- [Run analysis tools](#run-analysis-tools)
- [Interactive shell](#interactive-shell)
    - [Docker Compose (dashboard + analysis)](#docker-compose-dashboard-analysis)
- [docker-compose.yml](#docker-composeyml)
  - [Running Forgesmith (Self-Improvement Engine)](#running-forgesmith-self-improvement-engine)
- [Full analysis + apply changes](#full-analysis-apply-changes)
- [Dry run (analyze only, no changes applied)](#dry-run-analyze-only-no-changes-applied)
- [Report only](#report-only)
- [Propose prompt optimizations (OPRO-style)](#propose-prompt-optimizations-opro-style)
- [Rollback a specific run](#rollback-a-specific-run)
- [SIMBA rule generation](#simba-rule-generation)
- [GEPA prompt evolution](#gepa-prompt-evolution)
- [Backfill episode data from logs](#backfill-episode-data-from-logs)
  - [Running Tests](#running-tests)
- [Run all tests](#run-all-tests)
- [Run a specific test file](#run-a-specific-test-file)
- [Run tests without pytest (each file has a main())](#run-tests-without-pytest-each-file-has-a-main)
- [Benchmark database migrations](#benchmark-database-migrations)
  - [Troubleshooting](#troubleshooting)
    - [Database not found](#database-not-found)
- [OR](#or)
    - [Claude CLI not found](#claude-cli-not-found)
- [Verify installation](#verify-installation)
- [If using API directly, ensure the key is set](#if-using-api-directly-ensure-the-key-is-set)
    - [Database schema is outdated](#database-schema-is-outdated)
    - [Port / process conflicts (Ollama)](#port-process-conflicts-ollama)
- [Check if Ollama is running](#check-if-ollama-is-running)
- [Start Ollama](#start-ollama)
- [Or check health via the script](#or-check-health-via-the-script)
    - [Permission denied on project directories](#permission-denied-on-project-directories)
- [Check ownership](#check-ownership)
- [Fix if needed](#fix-if-needed)
    - [Agent stuck in infinite loop](#agent-stuck-in-infinite-loop)
- [Check loop detection thresholds in dispatch_config.json](#check-loop-detection-thresholds-in-dispatch_configjson)
- [Manually kill a stuck task (sets status to 'failed')](#manually-kill-a-stuck-task-sets-status-to-failed)
    - [Forgesmith rollback](#forgesmith-rollback)
- [List recent Forgesmith runs](#list-recent-forgesmith-runs)
- [Rollback a specific run](#rollback-a-specific-run)
- [Rollback autoresearch prompt changes](#rollback-autoresearch-prompt-changes)
    - [Tests fail with "no such table"](#tests-fail-with-no-such-table)
- [The test database may need initialization](#the-test-database-may-need-initialization)
- [Some tests create temporary databases — ensure /tmp is writable](#some-tests-create-temporary-databases-ensure-tmp-is-writable)
    - ["Too many API calls" / Rate limiting](#too-many-api-calls-rate-limiting)
  - [Architecture Quick Reference](#architecture-quick-reference)
  - [Related Documentation](#related-documentation)

## TL;DR

```bash
git clone <your-equipa-repo-url> && cd Equipa-repo
python3 equipa_setup.py                  # Interactive guided setup
python3 db_migrate.py                    # Ensure DB schema is current
python3 -m equipa.cli                    # Run the orchestrator
```

> EQUIPA is pure Python stdlib with zero pip dependencies. If you have Python 3.10+ and SQLite, you can run it.

---

## Prerequisites

| Requirement | Minimum Version | Check Command | Install Link |
|-------------|----------------|---------------|--------------|
| Python | 3.10+ | `python3 --version` | [python.org](https://www.python.org/downloads/) |
| SQLite | 3.35+ (bundled with Python) | `python3 -c "import sqlite3; print(sqlite3.sqlite_version)"` | Usually pre-installed |
| Git | 2.x | `git --version` | [git-scm.com](https://git-scm.com/) |
| Claude CLI / API key | Latest | `claude --version` | [Anthropic Console](https://console.anthropic.com/) |
| `gh` CLI (optional) | 2.x | `gh --version` | [cli.github.com](https://cli.github.com/) |
| Ollama (optional, for local models) | Latest | `ollama --version` | [ollama.com](https://ollama.com/) |

> **Note:** EQUIPA has **zero pip dependencies** — the entire core runs on Python's standard library. Optional components (Forgesmith GEPA with DSPy, Ollama agent) may have their own requirements.

---

## Step-by-Step Setup

### 1. Clone the repository

```bash
git clone <your-equipa-repo-url>
cd Equipa-repo
```

### 2. Run the interactive setup wizard

```bash
python3 equipa_setup.py
```

This will walk you through:
- Verifying prerequisites (`python3`, `sqlite3`, `git`, `claude`)
- Choosing an install path
- Creating and initializing the SQLite database
- Copying files into place
- Generating configuration files (`dispatch_config.json`, MCP config, `CLAUDE.md`)
- Optionally setting up Forgesmith cron, Sentinel, and ForgeBot

### 3. Run database migrations (if upgrading or starting fresh)

```bash
python3 db_migrate.py
```

This auto-detects the current schema version and applies incremental migrations (v0→v1→v2→v3→v4). A backup is created before each migration.

### 4. Verify the installation

```bash
python3 db_migrate.py              # Should print "Database is up to date"
python3 -m equipa.cli --help       # Show CLI options
python3 nightly_review.py          # Generate a portfolio status report
```

### 5. Run your first task

```bash
# Dispatch pending work automatically
python3 -m equipa.cli --auto

# Or dispatch a specific task by ID
python3 -m equipa.cli --task 42

# Or dispatch by goal file
python3 -m equipa.cli --goals goals.json
```

---

## Environment Variables

| Variable | Description | Example | Required? |
|----------|-------------|---------|-----------|
| `ANTHROPIC_API_KEY` | API key for Claude (Anthropic) | `sk-ant-api03-...` | **Yes** (unless using Ollama only) |
| `EQUIPA_DB` | Path to the SQLite database | `/home/user/equipa/equipa.db` | No — auto-detected from config |
| `EQUIPA_HOME` | Base directory for EQUIPA installation | `/home/user/equipa` | No — set during `equipa_setup.py` |
| `OLLAMA_BASE_URL` | Base URL for Ollama API (local models) | `http://localhost:11434` | No — only if using Ollama provider |
| `OLLAMA_MODEL` | Default Ollama model name | `codellama:13b` | No — configured in `dispatch_config.json` |
| `FORGESMITH_DRY_RUN` | Run Forgesmith analysis without applying changes | `1` | No — default is `0` |

> Most configuration lives in `dispatch_config.json` and the database itself, not environment variables. The setup wizard generates these files for you.

---

## Configuration Files

After running `equipa_setup.py`, you'll have:

| File | Purpose |
|------|---------|
| `dispatch_config.json` | Agent routing, model selection, feature flags, role prompts |
| `CLAUDE.md` | Project context injected into agent sessions |
| `.mcp.json` | MCP server configuration for Claude Desktop/CLI |
| `prompts/` | Role-specific system prompts (developer, tester, security, etc.) |
| `skills/` | Reusable skill definitions for agents |

### Editing dispatch config

```bash
# View current config
cat dispatch_config.json | python3 -m json.tool

# Key sections:
# - "roles": defines available agent roles
# - "features": feature flag toggles
# - "models": provider and model per role
# - "max_turns": turn budgets per complexity level
```

---

## Running in Production

### Option A: Cron-based (recommended for solo/small team)

The setup wizard can configure this automatically. Manually:

```bash
# Run Forgesmith optimizer nightly at 2 AM
crontab -e
```

```cron
# Forgesmith self-improvement loop
0 2 * * * cd /path/to/equipa && python3 forgesmith.py --full >> /var/log/equipa/forgesmith.log 2>&1

# Nightly review report
0 6 * * * cd /path/to/equipa && python3 nightly_review.py >> /var/log/equipa/nightly.log 2>&1

# Auto-dispatch pending work every 30 minutes
*/30 * * * * cd /path/to/equipa && python3 -m equipa.cli --auto >> /var/log/equipa/dispatch.log 2>&1
```

### Option B: systemd service

```ini
# /etc/systemd/system/equipa-dispatch.service
[Unit]
Description=EQUIPA Agent Dispatcher
After=network.target

[Service]
Type=oneshot
User=equipa
WorkingDirectory=/home/equipa/equipa
ExecStart=/usr/bin/python3 -m equipa.cli --auto
Environment=ANTHROPIC_API_KEY=sk-ant-api03-your-key-here
StandardOutput=append:/var/log/equipa/dispatch.log
StandardError=append:/var/log/equipa/dispatch.log

[Install]
WantedBy=multi-user.target
```

```ini
# /etc/systemd/system/equipa-dispatch.timer
[Unit]
Description=Run EQUIPA dispatch every 30 minutes

[Timer]
OnCalendar=*:0/30
Persistent=true

[Install]
WantedBy=timers.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now equipa-dispatch.timer
sudo systemctl status equipa-dispatch.timer
```

### Option C: PM2 (if you prefer Node-style process management)

```bash
pm2 start "python3 -m equipa.cli --auto" --name equipa-dispatch --cron "*/30 * * * *" --no-autorestart
pm2 save
```

---

## Docker

> **Note:** EQUIPA is designed to run directly on the host (it needs access to local git repos, the Claude CLI, and project directories). Docker is best suited for the database + dashboard components, not the full agent dispatch loop.

```dockerfile
# Dockerfile
FROM python:3.12-slim

# No pip install needed — zero dependencies
RUN apt-get update && apt-get install -y \
    git \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY . /app/

# Initialize database
RUN python3 db_migrate.py || true

# Default: run nightly review (swap for your use case)
CMD ["python3", "nightly_review.py"]
```

```bash
# Build
docker build -t equipa .

# Run nightly review
docker run --rm \
  -v /path/to/equipa.db:/app/equipa.db \
  -e ANTHROPIC_API_KEY=sk-ant-api03-your-key \
  equipa

# Run analysis tools
docker run --rm \
  -v /path/to/equipa.db:/app/equipa.db \
  equipa python3 analyze_performance.py

# Interactive shell
docker run -it --rm \
  -v /path/to/equipa.db:/app/equipa.db \
  equipa bash
```

### Docker Compose (dashboard + analysis)

```yaml
# docker-compose.yml
version: '3.8'
services:
  equipa-dashboard:
    build: .
    command: python3 tools/forge_dashboard.py
    volumes:
      - ./equipa.db:/app/equipa.db
    environment:
      - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}

  equipa-forgesmith:
    build: .
    command: python3 forgesmith.py --full
    volumes:
      - ./equipa.db:/app/equipa.db
      - ./prompts:/app/prompts
      - ./backups:/app/backups
    environment:
      - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
```

---

## Running Forgesmith (Self-Improvement Engine)

Forgesmith analyzes agent performance and evolves prompts, configs, and rules.

```bash
# Full analysis + apply changes
python3 forgesmith.py --full

# Dry run (analyze only, no changes applied)
python3 forgesmith.py --full --dry-run

# Report only
python3 forgesmith.py --report

# Propose prompt optimizations (OPRO-style)
python3 forgesmith.py --propose

# Rollback a specific run
python3 forgesmith.py --rollback <run-id>

# SIMBA rule generation
python3 forgesmith_simba.py

# GEPA prompt evolution
python3 forgesmith_gepa.py --dry-run

# Backfill episode data from logs
python3 forgesmith_backfill.py
```

---

## Running Tests

```bash
# Run all tests
python3 -m pytest tests/ -v

# Run a specific test file
python3 -m pytest tests/test_early_termination.py -v

# Run tests without pytest (each file has a main())
python3 tests/test_lesson_sanitizer.py
python3 tests/test_loop_detection.py
python3 tests/test_agent_messages.py
python3 tests/test_agent_actions.py

# Benchmark database migrations
python3 tools/benchmark_migrations.py
```

---

## Troubleshooting

### Database not found

```
Error: Could not find equipa.db
```

**Fix:** Run the setup wizard or set the path explicitly:
```bash
python3 equipa_setup.py
# OR
export EQUIPA_DB=/path/to/your/equipa.db
```

### Claude CLI not found

```
Error: claude command not found
```

**Fix:** Install the Claude CLI and ensure it's on your PATH:
```bash
# Verify installation
which claude
claude --version

# If using API directly, ensure the key is set
export ANTHROPIC_API_KEY=sk-ant-api03-...
```

### Database schema is outdated

```
Error: no such column: task_type
```

**Fix:** Run migrations:
```bash
python3 db_migrate.py
```

A backup is automatically created before each migration.

### Port / process conflicts (Ollama)

```
Error: Connection refused to localhost:11434
```

**Fix:**
```bash
# Check if Ollama is running
curl http://localhost:11434/api/tags

# Start Ollama
ollama serve

# Or check health via the script
python3 -c "from ollama_agent import check_ollama_health; print(check_ollama_health('http://localhost:11434'))"
```

### Permission denied on project directories

```
Error: Permission denied: /path/to/project/.git
```

**Fix:** Ensure the user running EQUIPA has read/write access to all project directories referenced in the database.
```bash
# Check ownership
ls -la /path/to/project/

# Fix if needed
sudo chown -R $(whoami) /path/to/project/
```

### Agent stuck in infinite loop

EQUIPA has built-in loop detection (monologue detection, tool loop detection, alternating pattern detection). If an agent is still stuck:

```bash
# Check loop detection thresholds in dispatch_config.json
cat dispatch_config.json | python3 -c "import json,sys; c=json.load(sys.stdin); print(json.dumps(c.get('features',{}), indent=2))"

# Manually kill a stuck task (sets status to 'failed')
sqlite3 equipa.db "UPDATE tasks SET status='failed', result='Manually terminated' WHERE id=<task_id>;"
```

### Forgesmith rollback

If Forgesmith made a bad change:
```bash
# List recent Forgesmith runs
python3 forgesmith.py --report

# Rollback a specific run
python3 forgesmith.py --rollback <run-id>

# Rollback autoresearch prompt changes
python3 autoresearch_prompts.py --rollback
```

### Tests fail with "no such table"

```bash
# The test database may need initialization
python3 db_migrate.py

# Some tests create temporary databases — ensure /tmp is writable
ls -la /tmp/
```

### "Too many API calls" / Rate limiting

**Fix:** Adjust concurrency and cooldowns in `dispatch_config.json`:
```json
{
  "max_parallel": 2,
  "cooldown_seconds": 30
}
```

---

## Architecture Quick Reference

```
equipa/
├── cli.py              # Entry point: python3 -m equipa.cli
├── dispatch.py         # Task scoring, routing, parallel execution
├── agent_runner.py     # Subprocess management for agent calls
├── monitoring.py       # Loop detection, budget tracking
├── lessons.py          # Lesson + episode injection (SIMBA rules)
├── parsing.py          # Output parsing, reflection extraction
├── tasks.py            # Task fetching, status updates
├── db.py               # Database connection, schema management
├── prompts.py          # Checkpoint context building
├── security.py         # Skill integrity, content wrapping
└── git_ops.py          # Language detection, repo setup

forgesmith.py           # Self-improvement: analysis + changes
forgesmith_simba.py     # Rule generation from episodes
forgesmith_gepa.py      # Prompt evolution (GEPA/DSPy)
forgesmith_impact.py    # Change impact assessment
forgesmith_backfill.py  # Episode data backfill from logs
nightly_review.py       # Portfolio status report
db_migrate.py           # Schema migrations (v0→v4)
equipa_setup.py         # Interactive setup wizard
```
---

## Related Documentation

- [Architecture](ARCHITECTURE.md)
- [Api](API.md)
- [Contributing](CONTRIBUTING.md)
