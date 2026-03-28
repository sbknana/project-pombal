# DEPLOYMENT.md — EQUIPA

## Table of Contents

- [DEPLOYMENT.md — EQUIPA](#deploymentmd-equipa)
  - [TL;DR](#tldr)
- [Open Claude Desktop/Code and start talking. That's it.](#open-claude-desktopcode-and-start-talking-thats-it)
  - [How You Actually Use This](#how-you-actually-use-this)
  - [Prerequisites](#prerequisites)
  - [Step-by-Step Setup](#step-by-step-setup)
    - [1. Clone the repo](#1-clone-the-repo)
    - [2. Run the setup wizard (recommended)](#2-run-the-setup-wizard-recommended)
    - [3. Or do it manually](#3-or-do-it-manually)
    - [4. Configure MCP for Claude](#4-configure-mcp-for-claude)
    - [5. Verify it works](#5-verify-it-works)
    - [6. Run the test suite (optional but satisfying)](#6-run-the-test-suite-optional-but-satisfying)
  - [Environment Variables](#environment-variables)
  - [Running in Production](#running-in-production)
    - [Systemd (Linux)](#systemd-linux)
    - [ForgeSmith Cron (Self-Improvement)](#forgesmith-cron-self-improvement)
- [ForgeSmith full analysis — runs at 2am](#forgesmith-full-analysis-runs-at-2am)
- [SIMBA rule generation — runs at 3am](#simba-rule-generation-runs-at-3am)
- [Nightly review report](#nightly-review-report)
    - [PM2 (if you prefer it)](#pm2-if-you-prefer-it)
  - [Docker](#docker)
- [No pip install needed. Zero dependencies.](#no-pip-install-needed-zero-dependencies)
- [Create data directory for DB and logs](#create-data-directory-for-db-and-logs)
- [Initialize the database](#initialize-the-database)
- [MCP server](#mcp-server)
    - [Docker Compose (with Ollama for local embeddings)](#docker-compose-with-ollama-for-local-embeddings)
  - [Troubleshooting](#troubleshooting)
    - [Claude doesn't see EQUIPA tools](#claude-doesnt-see-equipa-tools)
- [Should start without errors. Ctrl+C to stop.](#should-start-without-errors-ctrlc-to-stop)
    - ["Database is locked"](#database-is-locked)
    - [Missing ANTHROPIC_API_KEY](#missing-anthropic_api_key)
- [Or add to your shell profile:](#or-add-to-your-shell-profile)
    - [Port already in use](#port-already-in-use)
    - [Database migration fails](#database-migration-fails)
- [Migrations auto-backup, so this is safe](#migrations-auto-backup-so-this-is-safe)
- [If that fails, check your current version:](#if-that-fails-check-your-current-version)
    - [Ollama connection refused](#ollama-connection-refused)
    - [Agent stuck in a loop](#agent-stuck-in-a-loop)
    - [Tests fail after fresh clone](#tests-fail-after-fresh-clone)
- [Make sure you're on Python 3.10+](#make-sure-youre-on-python-310)
- [Run from the repo root](#run-from-the-repo-root)
- [If specific tests fail about missing DB, ensure schema first:](#if-specific-tests-fail-about-missing-db-ensure-schema-first)
  - [Current Limitations](#current-limitations)
  - [Related Documentation](#related-documentation)

## TL;DR

```bash
git clone https://github.com/your-org/equipa-repo.git
cd equipa-repo
python3 equipa_setup.py          # interactive wizard — sets up DB, config, MCP
# Open Claude Desktop/Code and start talking. That's it.
```

If you want to skip the wizard and do it manually, keep reading.

---

## How You Actually Use This

**You don't type CLI commands.** You talk to Claude.

EQUIPA's primary interface is conversational. You open Claude (Desktop or Claude Code), say something like "add input validation to the signup form" or "write tests for the payment module", and Claude dispatches EQUIPA agents behind the scenes. It picks the right agent role, manages retries, tracks progress, and reports back.

The CLI (`equipa/cli.py`) exists for automation and scripting, but most people never touch it directly. The MCP server bridges Claude and EQUIPA — Claude talks to it over JSON-RPC, and everything happens from there.

Think of it like this: **you're the product manager, Claude is the engineering manager, EQUIPA agents are the engineers.**

---

## Prerequisites

| Tool | Version | Why | Install |
|------|---------|-----|---------|
| Python | 3.10+ | Runtime. That's the whole stack. | [python.org](https://www.python.org/downloads/) |
| SQLite | 3.35+ | Ships with Python. You already have it. | Built-in |
| Git | 2.30+ | Worktree isolation for parallel agents | [git-scm.com](https://git-scm.com/) |
| Claude Desktop or Claude Code | Latest | The conversational interface — where you actually work | [claude.ai/download](https://claude.ai/download) |
| `ANTHROPIC_API_KEY` | — | Agents use Claude API for reasoning | [console.anthropic.com](https://console.anthropic.com/) |

**Optional:**

| Tool | Version | Why |
|------|---------|-----|
| Ollama | 0.1.20+ | Local model support, vector embeddings | [ollama.com](https://ollama.com/) |
| `gh` CLI | 2.0+ | Auto PR creation, repo setup | `brew install gh` or [cli.github.com](https://cli.github.com/) |

**No pip install. No virtualenv. No requirements.txt.** It's pure Python stdlib. Copy the files and run.

---

## Step-by-Step Setup

### 1. Clone the repo

```bash
git clone https://github.com/your-org/equipa-repo.git
cd equipa-repo
```

### 2. Run the setup wizard (recommended)

```bash
python3 equipa_setup.py
```

This walks you through everything interactively:
- Creates the SQLite database (30+ tables)
- Generates `dispatch_config.json`
- Sets up MCP server config for Claude
- Generates `.mcp.json` and `CLAUDE.md` for your projects
- Optionally sets up ForgeSmith cron jobs
- Optionally configures Sentinel (monitoring) and ForgeBot

### 3. Or do it manually

#### Create the database

```bash
python3 -c "from equipa.db import ensure_schema; ensure_schema()"
```

#### Run migrations (if upgrading from an older version)

```bash
python3 db_migrate.py
```

This auto-detects your schema version and migrates forward. It backs up the DB first.

#### Set your API key

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
```

### 4. Configure MCP for Claude

Create `.mcp.json` in your project root (the setup wizard does this for you):

```json
{
  "mcpServers": {
    "equipa": {
      "command": "python3",
      "args": ["/path/to/equipa-repo/equipa/mcp_server.py"],
      "env": {
        "EQUIPA_DB": "/path/to/equipa-repo/forge.db",
        "ANTHROPIC_API_KEY": "sk-ant-..."
      }
    }
  }
}
```

Restart Claude Desktop/Code after adding this.

### 5. Verify it works

Open Claude and say: *"Show me the EQUIPA task board"* or *"What's the status of my projects?"*

If Claude responds with project data, you're good.

From the CLI (optional):

```bash
python3 -m equipa.cli --mcp-server  # starts MCP server manually
python3 -m equipa.cli --help         # see all CLI options
```

### 6. Run the test suite (optional but satisfying)

```bash
python3 -m pytest tests/ -v
```

334+ tests, all pure Python, no fixtures to install.

---

## Environment Variables

| Name | Description | Example | Required? |
|------|-------------|---------|-----------|
| `ANTHROPIC_API_KEY` | Claude API key for agent reasoning | `sk-ant-api03-...` | **Yes** |
| `EQUIPA_DB` | Path to SQLite database | `/home/user/equipa/forge.db` | No (defaults to `./forge.db`) |
| `EQUIPA_CONFIG` | Path to dispatch config | `/home/user/equipa/dispatch_config.json` | No (defaults to `./dispatch_config.json`) |
| `OLLAMA_BASE_URL` | Ollama server for local models / embeddings | `http://localhost:11434` | No |
| `EQUIPA_LOG_DIR` | Where agent logs go | `/home/user/equipa/logs` | No (defaults to `./logs`) |
| `FORGESMITH_DRY_RUN` | Run ForgeSmith analysis without applying changes | `1` | No |
| `EQUIPA_MAX_COST` | Global cost limit per agent run (USD) | `0.50` | No (has defaults per complexity) |

---

## Running in Production

### Systemd (Linux)

Create `/etc/systemd/system/equipa-mcp.service`:

```ini
[Unit]
Description=EQUIPA MCP Server
After=network.target

[Service]
Type=simple
User=deploy
WorkingDirectory=/opt/equipa
Environment=ANTHROPIC_API_KEY=sk-ant-...
Environment=EQUIPA_DB=/opt/equipa/forge.db
ExecStart=/usr/bin/python3 /opt/equipa/equipa/mcp_server.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable equipa-mcp
sudo systemctl start equipa-mcp
sudo journalctl -u equipa-mcp -f  # watch logs
```

### ForgeSmith Cron (Self-Improvement)

ForgeSmith analyzes agent performance and tunes prompts/config. Run it nightly:

```bash
crontab -e
```

```cron
# ForgeSmith full analysis — runs at 2am
0 2 * * * cd /opt/equipa && python3 forgesmith.py --mode full >> /opt/equipa/logs/forgesmith.log 2>&1

# SIMBA rule generation — runs at 3am
0 3 * * * cd /opt/equipa && python3 scripts/forgesmith_simba.py >> /opt/equipa/logs/simba.log 2>&1

# Nightly review report
0 6 * * * cd /opt/equipa && python3 scripts/nightly_review.py >> /opt/equipa/logs/nightly.log 2>&1
```

### PM2 (if you prefer it)

```bash
pm2 start "python3 /opt/equipa/equipa/mcp_server.py" --name equipa-mcp
pm2 save
pm2 startup
```

---

## Docker

EQUIPA doesn't need Docker — it's a handful of Python files and a SQLite database. But if you want containerization:

```dockerfile
FROM python:3.12-slim

WORKDIR /app

# No pip install needed. Zero dependencies.
COPY . /app

# Create data directory for DB and logs
RUN mkdir -p /data/logs

ENV EQUIPA_DB=/data/forge.db
ENV EQUIPA_LOG_DIR=/data/logs
ENV PYTHONUNBUFFERED=1

# Initialize the database
RUN python3 -c "import os; os.environ['EQUIPA_DB']='/data/forge.db'; from equipa.db import ensure_schema; ensure_schema()"

# MCP server
EXPOSE 3000
CMD ["python3", "equipa/mcp_server.py"]
```

```bash
docker build -t equipa .
docker run -d \
  --name equipa \
  -e ANTHROPIC_API_KEY=sk-ant-... \
  -v equipa-data:/data \
  equipa
```

### Docker Compose (with Ollama for local embeddings)

```yaml
version: '3.8'
services:
  equipa:
    build: .
    environment:
      - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
      - OLLAMA_BASE_URL=http://ollama:11434
      - EQUIPA_DB=/data/forge.db
    volumes:
      - equipa-data:/data
    depends_on:
      - ollama

  ollama:
    image: ollama/ollama
    volumes:
      - ollama-models:/root/.ollama

volumes:
  equipa-data:
  ollama-models:
```

---

## Troubleshooting

### Claude doesn't see EQUIPA tools

**Symptom:** You ask Claude to dispatch a task and it has no idea what you're talking about.

**Fix:** Check your `.mcp.json` path is correct. Restart Claude Desktop completely (not just close the window). Check the MCP server runs standalone:

```bash
python3 equipa/mcp_server.py
# Should start without errors. Ctrl+C to stop.
```

### "Database is locked"

**Symptom:** SQLite errors when multiple agents run in parallel.

**Fix:** This happens when too many agents write simultaneously. EQUIPA uses WAL mode by default. If you're seeing this:

```bash
python3 -c "
import sqlite3
conn = sqlite3.connect('forge.db')
conn.execute('PRAGMA journal_mode=WAL')
conn.close()
print('WAL mode enabled')
"
```

### Missing ANTHROPIC_API_KEY

**Symptom:** Agents fail immediately with authentication errors.

**Fix:**
```bash
export ANTHROPIC_API_KEY="sk-ant-api03-..."
# Or add to your shell profile:
echo 'export ANTHROPIC_API_KEY="sk-ant-..."' >> ~/.bashrc
```

### Port already in use

**Symptom:** MCP server won't start.

**Fix:**
```bash
lsof -i :3000  # find what's using the port
kill -9 <PID>  # kill it
```

### Database migration fails

**Symptom:** Errors about missing columns or tables after upgrading.

**Fix:**
```bash
# Migrations auto-backup, so this is safe
python3 db_migrate.py
# If that fails, check your current version:
python3 -c "
import sqlite3
conn = sqlite3.connect('forge.db')
print(conn.execute('SELECT value FROM schema_meta WHERE key=\"version\"').fetchone())
"
```

### Ollama connection refused

**Symptom:** Vector memory / embeddings don't work, but everything else is fine.

**Fix:** Ollama is optional. If you want it:
```bash
ollama serve                    # start the server
ollama pull nomic-embed-text    # pull an embedding model
curl http://localhost:11434/    # verify it's running
```

### Agent stuck in a loop

**Symptom:** Agent keeps reading the same files and burning through turns without making changes.

**Context:** EQUIPA has loop detection and early termination built in. But sometimes agents genuinely need many turns for complex tasks, and the 10-turn reading limit kills them too early. This is a known tension — see limitations below.

**Fix:** Check the agent logs in your log directory. If the task is legitimately complex, you can increase `max_turns` in `dispatch_config.json`.

### Tests fail after fresh clone

```bash
# Make sure you're on Python 3.10+
python3 --version

# Run from the repo root
cd equipa-repo
python3 -m pytest tests/ -v

# If specific tests fail about missing DB, ensure schema first:
python3 -c "from equipa.db import ensure_schema; ensure_schema()"
```

---

## Current Limitations

Being honest here:

- **Agents still get stuck on complex tasks.** Analysis paralysis is real — an agent will read 15 files trying to understand the codebase and burn through its turn budget before writing a single line of code. The early termination helps, but it's a blunt instrument.

- **Git worktree merges occasionally need manual intervention.** Parallel agents work in isolated worktrees, and most merges are clean. But when two agents touch the same file.. you're resolving that conflict yourself.

- **Self-improvement needs runway.** ForgeSmith, GEPA, and SIMBA need 20-30 completed tasks before patterns emerge. Before that, the feedback loop doesn't have enough data to do anything useful.

- **The Tester role depends on your project having a working test suite.** If your project doesn't have tests, the tester agent can't verify anything. It'll try to create tests, but it needs a test runner that actually works.

- **Early termination is aggressive.** Agents get killed at 10 turns of reading without writing. Some legitimate complex tasks (big refactors, cross-cutting concerns) genuinely need more exploration time. You can adjust this, but the defaults are tuned for cost control.

- **Cost controls kill runaway agents — sometimes too eagerly.** The cost breaker scales with task complexity, but it doesn't know if an agent is 90% done. A killed agent at 90% is worse than one that finishes at 110% budget.

- **It's not magic.** Agents still fail, get stuck, write bad code, and waste turns. EQUIPA makes them fail less often over time, but "less often" is not "never." Review what they produce.
---

## Related Documentation

- [Readme](README.md)
- [Architecture](ARCHITECTURE.md)
- [Api](API.md)
- [Contributing](CONTRIBUTING.md)
