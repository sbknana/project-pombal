<h1 align="center">EQUIPA</h1>

<p align="center">
  <strong>Your AI development team.</strong>
</p>

<p align="center">
  <em>European Portuguese for "team" — a self-improving AI agent orchestrator that builds, reviews, tests, and secures your code.</em>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.10%2B-blue?logo=python&logoColor=white" alt="Python 3.10+">
  <img src="https://img.shields.io/badge/dependencies-zero-brightgreen" alt="Zero Dependencies">
  <img src="https://img.shields.io/badge/license-MIT-orange" alt="MIT">
  <img src="https://img.shields.io/badge/tests-334%2B-success" alt="334+ Tests">
</p>

---

Software development takes dedication, perseverance, and knowledge. No tool changes that. What EQUIPA does is multiply your productivity — it handles the repetitive, parallelizable parts of the workflow so you can focus on the hard problems that actually need a human brain.

You talk to Claude. That's the interface. Describe what you want in plain English — "fix the login bug", "add search to the dashboard", "run a security review" — and Claude handles everything behind the scenes. It creates tasks, dispatches specialized AI agents, monitors their work, retries on failure, and reports results back to you. You never touch the orchestrator directly.

Then it gets better at its job. An autoresearch loop benchmarks agent performance, mutates prompts using genetic optimization, and commits or reverts based on results. Your agents tomorrow are measurably better than your agents today. Set it on a nightly cron and it improves itself while you sleep.

This is a productivity tool, not a magic wand. You still need to review the output, understand your codebase, and make the real decisions. EQUIPA just means you're not doing the grunt work alone.

---

## See It in Action

```
You: "Build user authentication with Google OAuth"

EQUIPA:
  Planning: broke feature into 5 tasks with dependency graph
  Tasks 1-3 dispatched in parallel (no dependencies)
  Task 4 waiting on task 2 (needs routes)
  Task 5 waiting on all (integration tests)

  OAuth config            -> src/config/auth.ts
  Login/callback routes   -> /auth/google, /auth/callback
  Session middleware       -> signed cookies
  Login UI component      -> Google branding guidelines
  8 integration tests     -> all passing

  "Want me to run a security review on the auth flow?"
```

```
You: "Users are getting 500 errors on checkout"

EQUIPA:
  Dispatched debugger agent
  Root cause: null pointer in calculateTotal() — discounted items with no original price
  Dispatched developer agent -> fix applied
  Dispatched tester agent -> 4 new edge case tests, all passing
  Done.
```

```
You: "Review the payment module for security issues"

EQUIPA:
  Dispatched security reviewer (Trail of Bits tooling)
  MEDIUM: Session tokens not rotated after privilege escalation
  LOW: CSRF token missing on logout endpoint
  "Want me to create fix tasks for these?"
```

You direct. EQUIPA executes. You review and decide what ships.

---

## What Makes EQUIPA Different

Most agent frameworks give you a library and tell you to build your own orchestration. EQUIPA gives you a **development team** — with memory, specialization, and the ability to learn from its own mistakes. You still drive. It just means you're not driving alone.

### Dev-Test Iteration Loop
Every coding task runs through a developer → tester cycle. If tests fail, the developer gets the failure context and tries again — up to 5 cycles. No human babysitting required.

### Self-Improving Agents
Three systems work together in a closed feedback loop:
- **ForgeSmith** extracts lessons from failures and tunes configuration
- **GEPA** evolves agent prompts through genetic optimization (validated at ICLR 2026)
- **SIMBA** synthesizes rules from recurring failure patterns

Lessons update episode quality scores. GEPA checks history before trying new prompt variants. SIMBA rules influence which past experiences get surfaced. The loop closes automatically.

### Episodic Memory
Every task outcome is stored as an episode with a quality score. When similar tasks come up, EQUIPA retrieves relevant past experiences and injects them into the agent's context. Agents build on what worked and avoid repeating failures.

### Nine Specialized Roles

| Role | What It Does |
|------|-------------|
| **Developer** | Writes code. Loads codebase navigation, implementation planning, and error recovery skills. |
| **Tester** | Writes and runs tests. Validates developer output. Iterates in dev-test loops. |
| **Security Reviewer** | Deep audit with 7 Trail of Bits skills. Static analysis, variant analysis, sharp-edge detection. |
| **Code Reviewer** | Quality, patterns, best practices. Architecture-level feedback. |
| **Debugger** | Investigates bugs with hypothesis-driven 5-step methodology. Traces root causes. |
| **Planner** | Breaks complex features into task lists with dependency graphs. |
| **Frontend Designer** | UI/UX focused development. |
| **Evaluator** | Assesses implementations against requirements. |
| **Integration Tester** | Tests how components work together across boundaries. |

### Language-Aware Prompts
EQUIPA detects your project's language (Python, TypeScript, Go, C#, Java, Rust, JavaScript) and injects language-specific best practices into agent prompts. Agents write idiomatic code for your stack without being told.

### Git Worktree Isolation
When running multiple tasks in parallel, each gets its own git branch via worktrees. Changes are isolated — one task can't break another. Successful work merges back automatically. This feature is actively being refined — merge reliability improves with each release.

### Cost Controls
Per-task budgets scale by complexity. Dynamic turn allocation. Real-time cost tracking. Agents that waste turns reading without writing get warned at turn 5, final warning at turn 8, and killed at turn 10. You set the limits, EQUIPA enforces them.

### Anti-Compaction State Persistence
Long tasks that fill the LLM context window don't lose progress. Agents maintain a state file on disk tracking what they've done and what's next. If context compacts mid-task, they read the state file and continue.

### Zero Dependencies
Pure Python standard library. No pip install, no virtualenv, no dependency conflicts. Copy the folder, run the script. Works on any machine with Python 3.10+.

---

## Architecture

EQUIPA is organized as a Python package with 21 focused modules:

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
```

The original `forge_orchestrator.py` is a 26-line backward-compatibility shim. All implementation lives in the package.

---

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

---

## Current Limitations

We believe in being honest about what doesn't work yet:

- **Agents still get stuck.** Complex tasks with large codebases can trigger analysis paralysis — agents read for 10 turns without writing. The early termination system catches this, but it means some tasks need multiple attempts.
- **Git worktree merges need work.** Parallel task merges occasionally fail or need manual intervention. We're actively improving merge verification.
- **Self-improvement takes time.** ForgeSmith needs 20-30 task completions before patterns emerge. Don't expect overnight results.
- **Tester depends on your tests.** The dev-test loop only works if your project has a working test suite. No tests = no iteration loop.
- **Context limits are real.** Very long tasks can exhaust the LLM context window. Anti-compaction state helps but doesn't eliminate the problem.

---

## Documentation

- [Quick Start](docs/QUICKSTART.md)
- [User Guide](docs/USER_GUIDE.md)
- [Architecture](docs/ARCHITECTURE.md)
- [API Reference](docs/API.md)
- [Deployment](docs/DEPLOYMENT.md)
- [Contributing](docs/CONTRIBUTING.md)
- [Custom Agents](docs/CUSTOM_AGENTS.md)
- [Local LLM Support](docs/LOCAL_LLM.md)
- [Concurrency Guide](docs/CONCURRENCY.md)
- [Training](docs/TRAINING.md)

## License

MIT

## Credits

Built by [Forgeborn](https://forgeborn.dev). Vibe coded with Claude.
