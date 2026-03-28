# EQUIPA

## Table of Contents

- [EQUIPA](#equipa)
  - [What is this?](#what-is-this)
  - [What is this? (continued)](#what-is-this-continued)
  - [Screenshots](#screenshots)
    - [Dashboard Overview](#dashboard-overview)
    - [Task Dispatch](#task-dispatch)
    - [Agent Logs](#agent-logs)
    - [ForgeSmith Self-Improvement](#forgesmith-self-improvement)
    - [Nightly Review](#nightly-review)
  - [Quick Start](#quick-start)
  - [How to Use](#how-to-use)
    - [The Conversational Way (recommended)](#the-conversational-way-recommended)
    - [The Dev-Test Loop](#the-dev-test-loop)
    - [Agent Roles](#agent-roles)
    - [The Self-Improvement Loop](#the-self-improvement-loop)
  - [Features](#features)
  - [Limitations](#limitations)
  - [Installation](#installation)
    - [Prerequisites](#prerequisites)
    - [Setup](#setup)
    - [Manual Setup](#manual-setup)
- [Create the database](#create-the-database)
- [Run migrations (if upgrading)](#run-migrations-if-upgrading)
- [Copy the example config](#copy-the-example-config)
- [Start the MCP server](#start-the-mcp-server)
    - [Environment Variables](#environment-variables)
  - [Configuration](#configuration)
  - [Tech Stack](#tech-stack)
    - [Project Structure](#project-structure)
    - [Running Tests](#running-tests)
  - [License](#license)
  - [Related Documentation](#related-documentation)

**Your AI development team — talk to Claude, it handles the rest.**

![EQUIPA Dashboard](screenshots/dashboard.png)

## What is this?

EQUIPA is a multi-agent AI orchestrator. You talk to Claude in plain English — "add dark mode to the settings page" or "fix the failing auth tests" — and Claude breaks it into tasks, dispatches specialized AI agents, watches them work, and reports back. You don't need to learn a CLI or memorize commands. Just have a conversation.

The name is European Portuguese for "team." That's what it is — a team of AI agents that write code, run tests, review for security issues, and get better at their jobs over time.

## What is this? (continued)

Here's the key thing: **you talk to Claude, Claude talks to EQUIPA.** The conversational interface is the primary way to use it. Claude dispatches tasks, monitors agents, handles failures, and gives you a summary. There's a CLI for automation and scripting, but most people never touch it.

## Screenshots

### Dashboard Overview
![Dashboard](screenshots/dashboard.png)
*The main dashboard showing active projects, task progress, and agent activity across your portfolio.*

### Task Dispatch
![Task Dispatch](screenshots/dispatch.png)
*When you tell Claude to work on something, it creates tasks and dispatches agents. This is what that looks like behind the scenes.*

### Agent Logs
![Agent Logs](screenshots/agent-logs.png)
*Every agent run is logged — what it tried, what worked, what failed. Useful for debugging when things go sideways.*

### ForgeSmith Self-Improvement
![ForgeSmith](screenshots/forgesmith.png)
*ForgeSmith analyzes agent performance over time and tunes prompts, configs, and rules. It needs 20-30 tasks before patterns start emerging.*

### Nightly Review
![Nightly Review](screenshots/nightly-review.png)
*A daily summary of what got done, what's blocked, and what needs attention. Runs automatically via cron.*

## Quick Start

1. **Clone the repo and run setup:**
   ```bash
   git clone https://github.com/your-org/equipa.git
   cd equipa
   python3 equipa_setup.py
   ```
   The setup wizard walks you through everything — database creation, config files, MCP integration.

2. **Start Claude with EQUIPA's MCP server:**
   ```bash
   python3 -m equipa.mcp_server
   ```
   Or let the setup wizard configure it for Claude Desktop/Code automatically.

3. **Talk to Claude:**
   > "Hey Claude, I need a function that validates email addresses in `utils/validation.py`. Write it and add tests."

   That's it. Claude creates the task, picks the right agent, dispatches it, and tells you when it's done.

4. **Check on things:**
   > "What's the status of my tasks?"
   > "Show me what the agents did today."
   > "Anything blocked?"

5. **Let ForgeSmith learn (optional):**
   ```bash
   python3 forgesmith.py --dry-run
   ```
   After 20-30 completed tasks, ForgeSmith starts noticing patterns — which agents struggle with what, which prompts work better — and makes adjustments.

## How to Use

### The Conversational Way (recommended)

Just talk to Claude. Seriously.

- **"Add input validation to the signup form"** — Claude creates a developer task, dispatches an agent to your project, the agent reads your code, makes changes, and runs your tests until they pass.
- **"Review the auth module for security issues"** — Claude dispatches a security reviewer agent that scans your code and reports findings.
- **"The login tests are broken, fix them"** — Claude sends a tester agent that reads the failures, fixes the tests, and verifies they pass.
- **"What happened with that refactoring task?"** — Claude checks the task status, reads the agent logs, and gives you a summary.

You don't manage agents. You don't pick models. You don't configure anything mid-conversation. Claude handles all of that through EQUIPA's MCP interface.

### The Dev-Test Loop

This is where EQUIPA earns its keep. When a developer agent writes code:

1. A tester agent runs the test suite
2. If tests fail, the developer gets the failure output and tries again
3. This loops until tests pass or the budget runs out

It's not magic — agents still write buggy code sometimes. But the retry loop catches a lot of issues that would otherwise land in your PR.

### Agent Roles

EQUIPA has 9 specialized agent roles:

- **Developer** — writes code, implements features, fixes bugs
- **Tester** — writes and runs tests, verifies behavior
- **Security Reviewer** — scans for vulnerabilities, reviews for security patterns
- **Planner** — breaks down complex tasks into subtasks
- **Evaluator** — reviews completed work for quality
- **Documenter** — writes docs, READMEs, inline comments
- **Researcher** — investigates technical questions, analyzes codebases
- **Refactorer** — improves code structure without changing behavior
- **DevOps** — handles CI/CD, deployment configs, infrastructure

Each role has language-aware prompts. If your project is Python, the developer agent gets Python-specific guidance. Same for TypeScript, Go, Rust, C#, and Java.

### The Self-Improvement Loop

This is the part that makes EQUIPA different from just running Claude on a task.

**ForgeSmith** watches every agent run — what worked, what failed, how many turns it took, what errors came up. After enough data (20-30 tasks, realistically), three systems kick in:

- **GEPA** (Guided Evolutionary Prompt Adaptation) — evolves agent prompts based on what's actually working. A/B tests new prompts against existing ones.
- **SIMBA** (Strategy Injection via Memory-Based Augmentation) — extracts tactical rules from success/failure patterns and injects them into future runs.
- **Episodic Memory** — agents remember past experiences. Similar tasks get relevant context from previous attempts, including what went wrong.

It's a closed loop: agents work → ForgeSmith learns → agents get better → ForgeSmith learns more.

But let's be honest: this takes time. Don't expect dramatic improvement after 5 tasks.

## Features

- **Talk to Claude, get code** — no CLI to learn, no commands to memorize. Say what you want in plain English.
- **Dev-test retry loop** — agents keep trying until tests pass, not just until they think they're done.
- **Self-improving agents** — prompts, rules, and strategies evolve based on real performance data.
- **Zero dependencies** — pure Python stdlib. No pip install, no virtualenv, no dependency hell. Copy it and run it.
- **9 specialized roles** — each agent knows its job. A tester tests. A reviewer reviews. No jack-of-all-trades confusion.
- **Language-aware prompts** — agents get guidance specific to your project's language and framework.
- **Cost controls that actually work** — budget limits per task, per complexity tier. Runaway agents get killed, not just warned.
- **Anti-compaction state persistence** — long tasks don't lose context when Claude's context window fills up. State is preserved across turns.
- **Episodic memory with knowledge graphs** — agents remember past work and retrieve relevant experience for new tasks.
- **Loop detection** — catches agents that are stuck repeating the same action and terminates them.
- **Nightly reviews** — automated portfolio summary of what got done, what's blocked, and what needs attention.
- **MCP server** — Claude connects via Model Context Protocol for native integration.
- **Skill integrity verification** — SHA-256 manifest ensures agent skills haven't been tampered with.
- **Lesson sanitization** — prompt injection protection on learned lessons. No one sneaks malicious instructions into agent memory.

## Limitations

Being honest here:

- **Agents still get stuck.** Complex tasks with ambiguous requirements cause analysis paralysis. An agent will read files for 10 turns, never write a line of code, and get terminated. This happens more often than we'd like.
- **Early termination is aggressive.** Agents get killed after 10 turns of just reading without writing. Some legitimate complex tasks genuinely need that many turns to understand the codebase. We're still tuning this.
- **Git worktree merges occasionally need manual intervention.** Agents work in isolated worktrees, but merging back sometimes conflicts. You'll need to resolve these yourself.
- **Self-improvement needs volume.** ForgeSmith needs 20-30 completed tasks before patterns emerge. Before that, it's just collecting data. Don't expect miracles on day one.
- **The tester role assumes you have tests.** If your project doesn't have a working test suite, the dev-test loop doesn't help much. The tester agent can *write* tests, but it needs something to run.
- **Agents are not magic.** They still fail, get confused, waste turns, and produce mediocre code. The system makes them *better over time*, but "better" is relative. Review their output.
- **Ollama support is experimental.** You can run agents via local Ollama models, but quality drops significantly compared to Claude. It's there for cost-sensitive or offline use cases.
- **Cost tracking is approximate.** Token counts are estimated, not exact. Budget limits work but don't expect penny-precise accounting.

## Installation

### Prerequisites

- **Python 3.10+** (no pip packages needed — really, zero)
- **SQLite 3.35+** (comes with Python, but check if you're on an old system)
- **Claude CLI or Claude Desktop** (for the conversational interface)
- **Git** (for worktree isolation)
- **GitHub CLI (`gh`)** — optional, for PR creation

### Setup

The interactive setup wizard handles everything:

```bash
git clone https://github.com/your-org/equipa.git
cd equipa
python3 equipa_setup.py
```

It will:
1. Check prerequisites
2. Create the SQLite database with 30+ tables
3. Generate `dispatch_config.json` with sensible defaults
4. Configure MCP integration for Claude
5. Generate `CLAUDE.md` project context
6. Optionally set up ForgeSmith cron jobs

### Manual Setup

If you prefer doing things yourself:

```bash
# Create the database
python3 -c "from equipa.db import ensure_schema; ensure_schema()"

# Run migrations (if upgrading)
python3 db_migrate.py

# Copy the example config
cp dispatch_config.example.json dispatch_config.json

# Start the MCP server
python3 -m equipa.mcp_server
```

### Environment Variables

| Variable | Purpose | Default |
|----------|---------|---------|
| `EQUIPA_DB` | Path to SQLite database | `./equipa.db` |
| `EQUIPA_CONFIG` | Path to dispatch config | `./dispatch_config.json` |
| `ANTHROPIC_API_KEY` | For Claude API calls (ForgeSmith) | — |
| `OLLAMA_BASE_URL` | For local model support | `http://localhost:11434` |

## Configuration

The main config file is `dispatch_config.json`. Key settings:

```json
{
  "max_turns": 30,
  "cost_limit_per_task": 0.50,
  "auto_routing": true,
  "features": {
    "episodic_memory": true,
    "vector_memory": false,
    "knowledge_graph": false,
    "simba_rules": true,
    "lesson_injection": true
  },
  "model_overrides": {
    "developer": "claude-sonnet-4-20250514",
    "tester": "claude-sonnet-4-20250514",
    "security_reviewer": "claude-sonnet-4-20250514"
  }
}
```

**`auto_routing`** — when enabled, EQUIPA picks the model tier based on task complexity. Simple tasks get cheaper models. Complex ones get the big guns. Saves money without sacrificing quality on hard problems.

**`features`** — toggle individual subsystems. Vector memory and knowledge graphs require Ollama for embeddings. Everything else works out of the box.

**`cost_limit_per_task`** — hard cap on spending per agent run. When an agent hits this, it's terminated. No exceptions. Set this before you forget.

**`max_turns`** — how many conversation turns an agent gets before being cut off. Scales with task complexity if auto-routing is on.

## Tech Stack

For folks who want to contribute or understand the internals:

- **Python 3.10+** — pure stdlib, no external packages
- **SQLite** — single-file database, 30+ tables, managed via `db_migrate.py`
- **MCP (Model Context Protocol)** — Claude integration via JSON-RPC over stdio
- **Claude API** — for ForgeSmith's self-improvement loops (GEPA, SIMBA)
- **Ollama** — optional, for local embeddings and experimental local agent runs
- **Git worktrees** — agent isolation (each agent works in its own worktree)

### Project Structure

```
equipa/              # Core package (21 modules)
├── cli.py           # CLI entry point
├── dispatch.py      # Task scoring and agent dispatch
├── mcp_server.py    # MCP server for Claude integration
├── monitoring.py    # Loop detection, budget tracking
├── routing.py       # Model selection, cost routing
├── lessons.py       # Lesson and episode injection
├── graph.py         # Knowledge graph for episodic memory
├── embeddings.py    # Vector similarity (Ollama)
└── ...
forgesmith.py        # Self-improvement engine
forgesmith_gepa.py   # Prompt evolution (GEPA)
forgesmith_simba.py  # Rule extraction (SIMBA)
skills/              # Agent skill definitions
prompts/             # Role-specific and language-specific prompts
tests/               # 334+ tests
```

### Running Tests

```bash
python3 -m pytest tests/ -v
```

All tests run against SQLite in-memory databases. No external services needed.

## License

MIT

---

*EQUIPA — because "team" sounds better in Portuguese.*
---

## Related Documentation

- [Architecture](ARCHITECTURE.md)
- [Api](API.md)
- [Deployment](DEPLOYMENT.md)
- [Contributing](CONTRIBUTING.md)
