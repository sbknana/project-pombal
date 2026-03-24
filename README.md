# EQUIPA

A multi-agent orchestrator for AI coding tasks. Tell it what you want in plain English, and it coordinates specialized agents to get it done.

Built in pure Python. No dependencies to install.

## What It Does

EQUIPA takes a task description from your project database, picks the right agent role (developer, tester, security reviewer, etc.), dispatches it, monitors progress, and iterates until the work passes tests. If an agent gets stuck, EQUIPA kills it and tries a different approach.

It's not magic. Agents still fail, get confused, and occasionally waste time reading code they should be writing. But EQUIPA catches those patterns and adapts — both within a task (early termination, retries) and across tasks (lessons learned, prompt evolution).

## Top Features

### 1. Dev-Test Iteration Loop
Every coding task runs through a developer → tester cycle. If tests fail, the developer gets the failure context and tries again — up to 5 cycles. You don't babysit it.

### 2. Self-Improving Agents
EQUIPA learns from every task it runs. Three systems work together:
- **ForgeSmith** extracts lessons from failures and tunes configuration
- **GEPA** evolves agent prompts through genetic optimization (validated at ICLR 2026)
- **SIMBA** synthesizes rules from recurring failure patterns

These systems also share data — lessons update the quality scores of past experiences, GEPA checks history before trying new prompt variants, and SIMBA rules influence which past experiences get surfaced for future tasks.

### 3. Episodic Memory
Every task outcome is stored as an episode with a quality score. When similar tasks come up, EQUIPA retrieves relevant past experiences and injects them into the agent's context. Agents build on what worked before and avoid repeating failures.

### 4. Nine Specialized Roles
`developer` · `tester` · `planner` · `evaluator` · `security-reviewer` · `frontend-designer` · `debugger` · `code-reviewer` · `integration-tester`

Each role gets tailored prompts, skills, and turn budgets. A security reviewer thinks differently than a frontend designer.

### 5. Git Worktree Isolation
When running multiple tasks in parallel, each gets its own git branch via worktrees. Changes are isolated — one task can't break another. Successful work merges back to main automatically. Work in progress is still being refined — we're actively improving the merge reliability.

### 6. Language-Aware Prompts
EQUIPA detects your project's language (Python, TypeScript, Go, C#, Java, Rust, JavaScript) and injects language-specific best practices into agent prompts. Agents write idiomatic code for your stack without being told.

### 7. Cost Controls
Per-task budgets scale by complexity. Dynamic turn allocation. Real-time cost tracking. Agents that waste turns reading without writing get warned and eventually killed. You set the limits, EQUIPA enforces them.

### 8. Anti-Compaction State Persistence
Long tasks that fill the LLM context window don't lose progress. Agents maintain a state file on disk tracking what they've done and what's next. If context compacts mid-task, they read the state file and continue.

### 9. Zero Dependencies
Pure Python standard library. No pip install, no virtualenv, no dependency conflicts. Copy the folder, run the script. Works on any machine with Python 3.10+.

## Quick Start

```bash
# Clone
git clone https://github.com/sbknana/equipa.git
cd equipa

# Setup (interactive wizard)
python equipa_setup.py

# Run a single task
python forge_orchestrator.py --task 42 --dev-test -y

# Run tasks in parallel
python forge_orchestrator.py --tasks 42,43,44 --dev-test -y

# Auto-dispatch all pending work
python forge_orchestrator.py --dispatch -y

# Run self-improvement
python forgesmith.py --auto
```

## Architecture

```
equipa/                  # 21 modules (~280 lines each)
├── cli.py               # Entry point and argument parsing
├── dispatch.py           # Task scanning, scoring, parallel dispatch
├── loops.py              # Dev-test iteration loop
├── agent_runner.py       # Agent subprocess management and streaming
├── prompts.py            # System prompt construction
├── monitoring.py         # Stuck detection, loop detection, cost tracking
├── db.py                 # Database connection and schema management
├── tasks.py              # Task fetching and project context
├── lessons.py            # Episodic memory, Q-values, SIMBA integration
├── parsing.py            # Agent output parsing and compaction
├── security.py           # Skill integrity verification, untrusted markers
├── preflight.py          # Build checking, dependency installation
├── checkpoints.py        # Task checkpointing for crash recovery
├── messages.py           # Inter-agent messaging
├── reflexion.py          # Failure classification and reflection
├── manager.py            # Planner and evaluator agent coordination
├── roles.py              # Role configuration and cost tracking
├── constants.py          # Configuration constants
├── git_ops.py            # Git operations and language detection
├── output.py             # Logging and summary formatting
└── config.py             # Config file loading

prompts/                 # Agent role prompts
├── _common.md            # Shared instructions for all agents
├── developer.md          # Developer role prompt
├── tester.md             # Tester role prompt
├── ...                   # Other role prompts
└── languages/            # Language-specific best practices
    ├── python.md
    ├── typescript.md
    ├── go.md
    └── ...

skills/                  # Per-role skill libraries
├── developer/
├── tester/
├── debugger/
├── code-reviewer/
└── security/             # 7 Trail of Bits security skills

forgesmith.py            # Self-improvement engine
forgesmith_gepa.py       # Genetic prompt evolution
forgesmith_simba.py      # Rule synthesis from failure patterns
forgesmith_impact.py     # Blast-radius assessment for changes
```

## How It Works

1. You create tasks in a SQLite database (or use `--goal` to describe what you want)
2. EQUIPA reads the task, loads project context, and picks the right agent role
3. The agent runs as a subprocess (`claude -p` or Ollama) with a tailored system prompt
4. EQUIPA monitors the agent's output in real-time — detecting stuck behavior, tool loops, and wasted turns
5. After the developer finishes, a tester agent verifies the work
6. If tests fail, the developer gets another cycle with failure context
7. Successful work is committed and merged. Failed work is preserved for review.
8. Every outcome is recorded as an episode for future learning

## Requirements

- Python 3.10+
- Claude Code CLI (`claude`) or Ollama for local LLM support
- SQLite (included in Python)
- Git (for worktree isolation)

## Configuration

Copy the example files and edit:

```bash
cp .env.example .env
cp dispatch_config.example.json dispatch_config.json
cp forge_config.example.json forge_config.json
cp mcp_config.example.json mcp_config.json
```

Or run the setup wizard: `python equipa_setup.py`

## Current Limitations

- Agents still get stuck on complex tasks, especially when codebases are large. The early termination system catches this but it means some tasks need multiple attempts.
- Git worktree merges work but occasionally need manual intervention for conflicts.
- Self-improvement takes time to show results — it needs 20-30 task completions before patterns emerge.
- The tester role depends on the project having a working test suite. No tests = no iteration loop.

## License

MIT

## Credits

Built by [Forgeborn](https://forgeborn.dev). Vibe coded with Claude.
