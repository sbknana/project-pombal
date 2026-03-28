# API.md — EQUIPA

## Table of Contents

- [API.md — EQUIPA](#apimd-equipa)
  - [Overview](#overview)
  - [MCP Server (Primary Interface)](#mcp-server-primary-interface)
    - [Starting the Server](#starting-the-server)
- [or](#or)
    - [Available Tools](#available-tools)
    - [Request Format](#request-format)
    - [Initialization Handshake](#initialization-handshake)
    - [Listing Available Tools](#listing-available-tools)
  - [CLI Interface](#cli-interface)
    - [Basic Commands](#basic-commands)
- [Dispatch work automatically based on priority scoring](#dispatch-work-automatically-based-on-priority-scoring)
- [Dispatch specific tasks by ID](#dispatch-specific-tasks-by-id)
- [Run with goals file](#run-with-goals-file)
- [Start MCP server mode](#start-mcp-server-mode)
    - [Key CLI Functions (inferred)](#key-cli-functions-inferred)
  - [Internal APIs (Module-Level)](#internal-apis-module-level)
    - [Task Operations — `equipa/tasks.py`](#task-operations-equipataskspy)
- [Get a specific task](#get-a-specific-task)
- [Get next available task for a project](#get-next-available-task-for-a-project)
- [Get full project context](#get-full-project-context)
- [Get project metadata](#get-project-metadata)
- [Bulk fetch](#bulk-fetch)
- [Check complexity tier](#check-complexity-tier)
- [Verify a task was actually updated in DB](#verify-a-task-was-actually-updated-in-db)
- [Resolve where the project code lives on disk](#resolve-where-the-project-code-lives-on-disk)
    - [Database — `equipa/db.py`](#database-equipadbpy)
- [Get a connection (write=True for mutations)](#get-a-connection-writetrue-for-mutations)
- [Ensure all tables exist](#ensure-all-tables-exist)
- [Classify an error string into a category](#classify-an-error-string-into-a-category)
- [Returns: "import" | "timeout" | "file_not_found" | "permission" | "syntax" | "test_failure" | "unknown"](#returns-import-timeout-file_not_found-permission-syntax-test_failure-unknown)
    - [Dispatch & Routing — `equipa/dispatch.py`](#dispatch-routing-equipadispatchpy)
- [Load config](#load-config)
- [Check feature flags](#check-feature-flags)
- [Scan for pending work across all projects](#scan-for-pending-work-across-all-projects)
- [Score and prioritize](#score-and-prioritize)
- [Filter based on config rules](#filter-based-on-config-rules)
- [Dispatch (async)](#dispatch-async)
- [Parse task IDs from CLI string](#parse-task-ids-from-cli-string)
    - [Cost-Aware Model Routing — `equipa/routing.py`](#cost-aware-model-routing-equiparoutingpy)
- [Score a task's complexity (0.0 to 1.0)](#score-a-tasks-complexity-00-to-10)
- [Returns float — low scores get cheaper models, high scores get smarter ones](#returns-float-low-scores-get-cheaper-models-high-scores-get-smarter-ones)
- [Record whether a model succeeded (feeds circuit breaker)](#record-whether-a-model-succeeded-feeds-circuit-breaker)
    - [Lessons & Episodic Memory — `equipa/lessons.py`](#lessons-episodic-memory-equipalessonspy)
- [Track how many times a lesson was used](#track-how-many-times-a-lesson-was-used)
- [Get SIMBA rules that are currently active](#get-simba-rules-that-are-currently-active)
- [Track episode injection](#track-episode-injection)
    - [Embeddings & Vector Memory — `equipa/embeddings.py`](#embeddings-vector-memory-equipaembeddingspy)
- [Compare two embedding vectors](#compare-two-embedding-vectors)
- [Returns float between -1.0 and 1.0](#returns-float-between-10-and-10)
    - [Knowledge Graph — `equipa/graph.py`](#knowledge-graph-equipagraphpy)
- [Get the lesson/episode graph](#get-the-lessonepisode-graph)
- [Create edges between lessons that were used together](#create-edges-between-lessons-that-were-used-together)
    - [Hooks System — `equipa/hooks.py`](#hooks-system-equipahookspy)
- [Register a callback for an event](#register-a-callback-for-an-event)
- [Fire an event](#fire-an-event)
- [Async version](#async-version)
- [Load hooks from config file](#load-hooks-from-config-file)
- [Introspect](#introspect)
    - [Agent Output Parsing — `equipa/parsing.py`](#agent-output-parsing-equipaparsingpy)
- [Parse structured output from agents](#parse-structured-output-from-agents)
- [Validate agent output has required fields](#validate-agent-output-has-required-fields)
- [Compact output for storage (trim to max words)](#compact-output-for-storage-trim-to-max-words)
- [Rough token estimate](#rough-token-estimate)
- [Build context for retry cycles when tests fail](#build-context-for-retry-cycles-when-tests-fail)
    - [Monitoring — `equipa/monitoring.py`](#monitoring-equipamonitoringpy)
- [Detect when an agent is stuck in a loop](#detect-when-an-agent-is-stuck-in-a-loop)
- [Returns "ok", "warn", or "terminate"](#returns-ok-warn-or-terminate)
- [Calculate turn budget based on max_turns](#calculate-turn-budget-based-on-max_turns)
    - [MCP Health Monitoring — `equipa/mcp_health.py`](#mcp-health-monitoring-equipamcp_healthpy)
- [Check if a server is healthy](#check-if-a-server-is-healthy)
- [Mark outcomes](#mark-outcomes)
- [Unhealthy uses exponential backoff, capped at a max](#unhealthy-uses-exponential-backoff-capped-at-a-max)
- [Inspect](#inspect)
- [Clear](#clear)
    - [Security — `equipa/security.py`](#security-equipasecuritypy)
- [Wrap untrusted content with delimiters (anti-injection)](#wrap-untrusted-content-with-delimiters-anti-injection)
- [Generate integrity manifest for skill files](#generate-integrity-manifest-for-skill-files)
- [Write it to disk](#write-it-to-disk)
- [Verify nothing was tampered with](#verify-nothing-was-tampered-with)
    - [Git Operations — `equipa/git_ops.py`](#git-operations-equipagit_opspy)
- [Detect what language/framework a project uses](#detect-what-languageframework-a-project-uses)
- [Returns dict with 'languages' and 'frameworks' lists](#returns-dict-with-languages-and-frameworks-lists)
- [Check if GitHub CLI is available](#check-if-github-cli-is-available)
- [Set up all repos for dispatch](#set-up-all-repos-for-dispatch)
  - [ForgeSmith Self-Improvement APIs](#forgesmith-self-improvement-apis)
    - [ForgeSmith Core — `forgesmith.py`](#forgesmith-core-forgesmithpy)
- [Run full analysis + apply changes](#run-full-analysis-apply-changes)
- [Dry run (see what would change, don't apply)](#dry-run-see-what-would-change-dont-apply)
- [Report only](#report-only)
- [Propose prompt optimizations only](#propose-prompt-optimizations-only)
- [Rollback a specific run](#rollback-a-specific-run)
    - [GEPA (Prompt Evolution) — `forgesmith_gepa.py`](#gepa-prompt-evolution-forgesmith_gepapy)
    - [SIMBA (Rule Generation) — `forgesmith_simba.py`](#simba-rule-generation-forgesmith_simbapy)
  - [Error Handling](#error-handling)
    - [MCP Server Errors](#mcp-server-errors)
    - [Error Classification](#error-classification)
  - [Rate Limiting](#rate-limiting)
    - [Cost Breaker](#cost-breaker)
    - [Turn Limits](#turn-limits)
    - [Early Termination](#early-termination)
  - [Ollama Integration (Local Models)](#ollama-integration-local-models)
- [Check if Ollama is running](#check-if-ollama-is-running)
- [List available models](#list-available-models)
- [Chat completion](#chat-completion)
  - [Database Migrations — `db_migrate.py`](#database-migrations-db_migratepy)
- [Run all pending migrations](#run-all-pending-migrations)
- [Silent mode (no output)](#silent-mode-no-output)
  - [Current Limitations](#current-limitations)
  - [Related Documentation](#related-documentation)

## Overview

EQUIPA doesn't expose a traditional REST/GraphQL API. Instead, it communicates through two interfaces:

1. **MCP Server** — A JSON-RPC 2.0 server that Claude (or any MCP-compatible client) talks to over stdin/stdout. This is the primary interface. You don't call it directly — Claude does.
2. **CLI** — A command-line interface for scripting and automation. Most users never touch this because they just talk to Claude.

There are no HTTP endpoints, no REST routes, no GraphQL schemas. EQUIPA is a local tool that runs on your machine, backed by SQLite.

**Base communication:** JSON-RPC 2.0 over stdio (MCP protocol)
**Authentication:** None. It's local. If someone has access to your stdio pipe, you have bigger problems.
**Database:** SQLite, typically at `~/.forge/forge.db` or wherever you configured it.

---

## MCP Server (Primary Interface)

The MCP server is how Claude interacts with EQUIPA. When you talk to Claude and say "create a task to fix the login bug," Claude calls these tools behind the scenes.

### Starting the Server

```bash
python equipa/mcp_server.py
# or
python equipa/cli.py --mcp-server
```

The server speaks JSON-RPC 2.0 over stdin/stdout. You don't need to call it manually — your MCP client configuration handles this.

### Available Tools

These are the MCP tools Claude can invoke. Detected from `equipa/mcp_server.py` and test coverage in `tests/test_mcp_server.py`.

#### Task Management

| Tool | Description | Parameters | Response |
|------|-------------|------------|----------|
| `task_status` | Get the current status of a task | `task_id` (required, integer) | Task details: status, title, assignee, blockers, etc. |
| `task_create` | Create a new task | `title`, `description`, `project_id`, `priority`, `complexity` (inferred) | Created task ID and confirmation |
| `dispatch` | Dispatch a task to an agent | `task_id` (required) | Dispatch result or error if missing args |

#### Knowledge & Context

| Tool | Description | Parameters | Response |
|------|-------------|------------|----------|
| `lessons` | Retrieve learned lessons from past agent runs | None required (has defaults) | List of lessons with relevance scores |
| `agent_logs` | Get recent agent execution logs | None required (has defaults) | Log entries from recent runs |
| `session_notes` | Get session notes | None required (has defaults) | Notes from the current/recent sessions |
| `project_context` | Get full project context | `project_id` (required) | Project info, recent tasks, completion rates |

### Request Format

Standard MCP JSON-RPC 2.0:

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/call",
  "params": {
    "name": "task_status",
    "arguments": {
      "task_id": 42
    }
  }
}
```

### Initialization Handshake

Before calling tools, the MCP client must complete the initialization handshake:

```json
{
  "jsonrpc": "2.0",
  "id": 0,
  "method": "initialize",
  "params": {
    "protocolVersion": "2024-11-05",
    "capabilities": {},
    "clientInfo": { "name": "your-client", "version": "1.0" }
  }
}
```

Then send the initialized notification:

```json
{
  "jsonrpc": "2.0",
  "method": "notifications/initialized"
}
```

### Listing Available Tools

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/list"
}
```

Returns all available tools with their parameter schemas.

---

## CLI Interface

The CLI exists for automation, scripting, and when you want to bypass Claude. Most users don't need this — just talk to Claude.

### Basic Commands

```bash
# Dispatch work automatically based on priority scoring
python equipa/cli.py

# Dispatch specific tasks by ID
python equipa/cli.py --tasks 42,43,44

# Run with goals file
python equipa/cli.py --goals goals.yaml

# Start MCP server mode
python equipa/cli.py --mcp-server
```

### Key CLI Functions (inferred)

| Function | File | What It Does |
|----------|------|-------------|
| `main()` | `equipa/cli.py` | Entry point — parses args, decides mode |
| `async_main()` | `equipa/cli.py` | Async orchestration loop |
| `load_config()` | `equipa/cli.py` | Reads dispatch config |
| `get_provider(role, dispatch_config)` | `equipa/cli.py` | Picks AI provider per role |
| `get_ollama_model(role, dispatch_config)` | `equipa/cli.py` | Gets local model for role |

---

## Internal APIs (Module-Level)

These aren't network APIs — they're Python function interfaces you'd use if extending EQUIPA or building tools on top of it.

### Task Operations — `equipa/tasks.py`

```python
from equipa.tasks import fetch_task, fetch_next_todo, fetch_project_context

# Get a specific task
task = fetch_task(task_id=42)

# Get next available task for a project
task = fetch_next_todo(project_id=23)

# Get full project context
context = fetch_project_context(project_id=23)

# Get project metadata
info = fetch_project_info(project_id=23)

# Bulk fetch
tasks = fetch_tasks_by_ids([42, 43, 44])

# Check complexity tier
complexity = get_task_complexity(task)  # Returns "low", "medium", "high"

# Verify a task was actually updated in DB
verified = verify_task_updated(task_id=42)

# Resolve where the project code lives on disk
project_dir = resolve_project_dir(task)
```

### Database — `equipa/db.py`

```python
from equipa.db import get_db_connection, ensure_schema, classify_error

# Get a connection (write=True for mutations)
conn = get_db_connection(write=True)

# Ensure all tables exist
ensure_schema()

# Classify an error string into a category
error_type = classify_error("ModuleNotFoundError: No module named 'foo'")
# Returns: "import" | "timeout" | "file_not_found" | "permission" | "syntax" | "test_failure" | "unknown"
```

### Dispatch & Routing — `equipa/dispatch.py`

```python
from equipa.dispatch import (
    load_dispatch_config, scan_pending_work, score_project,
    apply_dispatch_filters, run_auto_dispatch, parse_task_ids,
    is_feature_enabled
)

# Load config
config = load_dispatch_config("dispatch_config.yaml")

# Check feature flags
enabled = is_feature_enabled(config, "vector_memory")

# Scan for pending work across all projects
work = scan_pending_work()

# Score and prioritize
scored = score_project(summary, config)

# Filter based on config rules
filtered = apply_dispatch_filters(work, config, args)

# Dispatch (async)
await run_auto_dispatch(scored, config, args)

# Parse task IDs from CLI string
ids = parse_task_ids("42,43,44")  # Returns [42, 43, 44]
```

### Cost-Aware Model Routing — `equipa/routing.py`

```python
from equipa.routing import score_complexity, record_model_outcome

# Score a task's complexity (0.0 to 1.0)
score = score_complexity(
    description="Fix the off-by-one error in the loop",
    title="Bug: pagination skips page 2"
)
# Returns float — low scores get cheaper models, high scores get smarter ones

# Record whether a model succeeded (feeds circuit breaker)
record_model_outcome(model="claude-sonnet", success=True)
```

The routing system has a circuit breaker pattern — if a model fails 5 times in a row, it degrades to a cheaper model until things recover. This is tested thoroughly in `tests/test_cost_routing.py`.

### Lessons & Episodic Memory — `equipa/lessons.py`

```python
from equipa.lessons import (
    update_lesson_injection_count,
    get_active_simba_rules,
    update_episode_injection_count
)

# Track how many times a lesson was used
update_lesson_injection_count(lesson_ids=[1, 2, 3])

# Get SIMBA rules that are currently active
rules = get_active_simba_rules()

# Track episode injection
update_episode_injection_count(episode_ids=[10, 11])
```

### Embeddings & Vector Memory — `equipa/embeddings.py`

```python
from equipa.embeddings import cosine_similarity

# Compare two embedding vectors
sim = cosine_similarity(vec_a, vec_b)
# Returns float between -1.0 and 1.0
```

Vector memory is optional — it uses a local Ollama instance for embeddings. When disabled, EQUIPA falls back to keyword-based retrieval. This is controlled via the `vector_memory` feature flag.

### Knowledge Graph — `equipa/graph.py`

```python
from equipa.graph import get_adjacency_list, create_coaccessed_edges

# Get the lesson/episode graph
adj = get_adjacency_list()

# Create edges between lessons that were used together
create_coaccessed_edges(lesson_ids=[1, 2, 3])
```

The graph is used to re-rank lessons by PageRank score — lessons that connect to other useful lessons get boosted. It's a nice idea that helps after you have enough data (20-30+ tasks).

### Hooks System — `equipa/hooks.py`

```python
from equipa.hooks import register, fire, fire_async, clear_registry

# Register a callback for an event
def on_task_complete(**kwargs):
    print(f"Task {kwargs['task_id']} done!")

register("task_complete", on_task_complete)

# Fire an event
fire("task_complete", task_id=42)

# Async version
await fire_async("task_complete", task_id=42)

# Load hooks from config file
load_hooks_config("hooks.yaml")

# Introspect
count = get_registered_count("task_complete")
```

### Agent Output Parsing — `equipa/parsing.py`

```python
from equipa.parsing import (
    parse_reflection, parse_approach_summary,
    parse_tester_output, parse_developer_output,
    validate_output, compact_agent_output,
    estimate_tokens, compute_keyword_overlap,
    build_test_failure_context
)

# Parse structured output from agents
reflection = parse_reflection(agent_output_text)
approach = parse_approach_summary(agent_output_text)
test_results = parse_tester_output(agent_output_text)
dev_results = parse_developer_output(agent_output_text)

# Validate agent output has required fields
is_valid = validate_output(result)

# Compact output for storage (trim to max words)
compacted = compact_agent_output(raw_output, max_words=500)

# Rough token estimate
tokens = estimate_tokens(text)

# Build context for retry cycles when tests fail
context = build_test_failure_context(test_results, cycle=2)
```

### Monitoring — `equipa/monitoring.py`

```python
from equipa.monitoring import LoopDetector, calculate_dynamic_budget

# Detect when an agent is stuck in a loop
detector = LoopDetector()
action = detector.record(fingerprint_data)
# Returns "ok", "warn", or "terminate"

if action == "warn":
    msg = detector.warning_message()
elif action == "terminate":
    summary = detector.termination_summary()

# Calculate turn budget based on max_turns
budget = calculate_dynamic_budget(max_turns=50)
```

The loop detector catches several patterns:
- Consecutive identical outputs
- Alternating between two states (A→B→A→B)
- Monologuing (text-only turns with no tool use)
- Same input producing same output repeatedly

### MCP Health Monitoring — `equipa/mcp_health.py`

```python
from equipa.mcp_health import MCPHealthMonitor

monitor = MCPHealthMonitor(cache_path="/tmp/mcp_health.json")

# Check if a server is healthy
if monitor.is_healthy("my-server"):
    # proceed
    pass

# Mark outcomes
monitor.mark_healthy("my-server")
monitor.mark_unhealthy("my-server", error="Connection refused")
# Unhealthy uses exponential backoff, capped at a max

# Inspect
status = monitor.get_status("my-server")
all_statuses = monitor.get_all_statuses()

# Clear
monitor.clear("my-server")  # Single
monitor.clear()  # All
```

Health state persists to a JSON file and survives restarts.

### Security — `equipa/security.py`

```python
from equipa.security import (
    wrap_untrusted, generate_skill_manifest,
    write_skill_manifest, verify_skill_integrity
)

# Wrap untrusted content with delimiters (anti-injection)
safe = wrap_untrusted(user_content, delimiter="TASK_INPUT")

# Generate integrity manifest for skill files
manifest = generate_skill_manifest()

# Write it to disk
write_skill_manifest()

# Verify nothing was tampered with
is_ok = verify_skill_integrity()
```

### Git Operations — `equipa/git_ops.py`

```python
from equipa.git_ops import detect_project_language, check_gh_installed, setup_all_repos

# Detect what language/framework a project uses
lang_info = detect_project_language("/path/to/project")
# Returns dict with 'languages' and 'frameworks' lists

# Check if GitHub CLI is available
has_gh = check_gh_installed()

# Set up all repos for dispatch
setup_all_repos(args)
```

Language detection looks at marker files (pyproject.toml → Python, tsconfig.json → TypeScript, etc.) and also detects frameworks (Django, FastAPI, Next.js, etc.).

---

## ForgeSmith Self-Improvement APIs

These are the internal APIs for EQUIPA's self-improvement loop. You probably won't call these directly, but they're documented for completeness.

### ForgeSmith Core — `forgesmith.py`

The main self-improvement engine. Analyzes agent runs, extracts lessons, proposes config changes.

```bash
# Run full analysis + apply changes
python forgesmith.py

# Dry run (see what would change, don't apply)
python forgesmith.py --dry-run

# Report only
python forgesmith.py --report

# Propose prompt optimizations only
python forgesmith.py --propose-only

# Rollback a specific run
python forgesmith.py --rollback <run_id>
```

Key internal functions:

| Function | What It Does |
|----------|-------------|
| `collect_agent_runs(cfg)` | Gathers recent agent execution data |
| `extract_lessons(runs, cfg)` | Derives lessons from successes/failures |
| `analyze_max_turns_hit(runs, cfg)` | Finds tasks that ran out of turns |
| `analyze_repeat_errors(runs, cfg)` | Spots recurring error patterns |
| `analyze_blocked_tasks(blocked, runs, cfg)` | Identifies why tasks are stuck |
| `apply_config_change(...)` | Changes a config value with rationale |
| `apply_prompt_patch(...)` | Modifies an agent's system prompt |
| `rollback_change(change)` | Reverts a previous change |
| `score_completed_runs(runs, cfg)` | Scores runs using the rubric system |
| `evolve_rubric_weights(cfg)` | Adjusts scoring weights based on outcomes |

### GEPA (Prompt Evolution) — `forgesmith_gepa.py`

Evolves agent system prompts using episode data. Think of it as automated prompt engineering.

```bash
python forgesmith_gepa.py
python forgesmith_gepa.py --dry-run
python forgesmith_gepa.py --role developer
```

| Function | What It Does |
|----------|-------------|
| `collect_episodes_for_role(role, days)` | Gets recent episodes for a role |
| `validate_evolved_prompt(current, evolved)` | Ensures evolution didn't break anything |
| `store_evolved_prompt(result, run_id, cfg, dry_run)` | Saves the new prompt version |
| `get_ab_prompt_for_role(role)` | Gets A/B test variant if one exists |
| `rollback_evolved_prompt(role, version)` | Reverts to a previous prompt version |

### SIMBA (Rule Generation) — `forgesmith_simba.py`

Generates behavioral rules from high-variance episodes. "If this situation, do this."

```bash
python forgesmith_simba.py
python forgesmith_simba.py --dry-run
python forgesmith_simba.py --role tester
```

| Function | What It Does |
|----------|-------------|
| `find_high_variance_episodes(days)` | Finds episodes with wildly different outcomes |
| `find_hardest_cases(days)` | Identifies consistently failing task types |
| `build_simba_prompt(...)` | Constructs the prompt for rule generation |
| `validate_rule(rule, existing)` | Checks rule isn't a duplicate or too vague |
| `store_rules(role, rules, dry_run)` | Saves rules to DB |
| `evaluate_simba_rules()` | Checks if existing rules are actually helping |
| `prune_stale_rules(dry_run)` | Removes rules that aren't effective |

---

## Error Handling

### MCP Server Errors

The MCP server returns standard JSON-RPC 2.0 errors:

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "error": {
    "code": -32602,
    "message": "Missing required argument: task_id"
  }
}
```

| Code | Meaning |
|------|---------|
| `-32700` | Parse error — invalid JSON |
| `-32601` | Method not found — unknown tool or method |
| `-32602` | Invalid params — missing or wrong arguments |
| `-32603` | Internal error — something broke |

### Error Classification

When agents fail, EQUIPA classifies errors into categories:

| Category | Pattern (inferred) |
|----------|-------------------|
| `timeout` | Execution timed out |
| `file_not_found` | File/path doesn't exist |
| `permission` | Permission denied |
| `syntax` | Syntax errors in code |
| `import` | Missing module/import failures |
| `test_failure` | Tests didn't pass |
| `unknown` | Everything else |

This classification feeds into ForgeSmith's pattern analysis — if the same error type keeps happening, it'll propose a fix.

---

## Rate Limiting

There's no traditional rate limiting (no HTTP server), but EQUIPA has several cost control mechanisms:

### Cost Breaker

Terminates agent runs that exceed a cost threshold. The limit scales with task complexity:

- **Low complexity:** Base cost limit
- **Medium complexity:** 2x base (inferred)
- **High complexity:** 3x base (inferred)

Configurable via `dispatch_config.yaml`.

### Turn Limits

Agents have a maximum turn budget. When they're running low, EQUIPA sends budget awareness messages:

| Checkpoint | Message Type |
|-----------|-------------|
| Every N turns | Periodic reminder |
| 50% turns used | Halfway warning |
| ~80% turns used | Critical warning |

### Early Termination

Agents get killed if they:
- Hit stuck phrases ("I need to think about this more..") for too many turns
- Enter a loop (same output 3+ times)
- Alternate between two states for 6+ cycles
- Monologue (text-only, no tool use) for 3+ consecutive turns after turn 5
- Read without writing for 10 turns (early termination)

---

## Ollama Integration (Local Models)

EQUIPA can use local models via Ollama as an alternative to Claude.

```python
from ollama_agent import ollama_chat, check_ollama_health, list_ollama_models

# Check if Ollama is running
healthy = check_ollama_health("http://localhost:11434")

# List available models
models = list_ollama_models("http://localhost:11434")

# Chat completion
response = ollama_chat(
    base_url="http://localhost:11434",
    model="codellama",
    messages=[{"role": "user", "content": "Fix this bug..."}],
    tools=None,
    timeout=120
)
```

The Ollama agent has its own sandboxed tool execution:

| Tool | Function | Write Access |
|------|----------|-------------|
| `read_file` | `exec_read_file()` | No |
| `list_directory` | `exec_list_directory()` | No |
| `search_files` | `exec_search_files()` | No |
| `grep` | `exec_grep()` | No |
| `bash` | `exec_bash()` | Configurable |
| `write_file` | `exec_write_file()` | Yes |
| `edit_file` | `exec_edit_file()` | Yes |

All paths are validated through `safe_path()` to prevent directory traversal. Commands are checked against `is_blocked_command()` before execution.

---

## Database Migrations — `db_migrate.py`

```bash
# Run all pending migrations
python db_migrate.py

# Silent mode (no output)
python db_migrate.py --silent
```

Current schema versions:

| Version | What Changed |
|---------|-------------|
| v0 → v1 | Initial schema normalization |
| v1 → v2 | Added agent episodes table |
| v2 → v3 | Added lessons and SIMBA rules |
| v3 → v4 | Added prompt versioning |
| v4 → v5 | Added embedding columns and knowledge graph table |

(inferred from migration functions)

Migrations create automatic backups before running. If something goes wrong, your data is safe.

---

## Current Limitations

- **No HTTP API.** EQUIPA is local-only. If you want a web API, you'd need to wrap it yourself.
- **MCP tool list is not self-documenting.** You need to call `tools/list` to see what's available, and even then the descriptions are whatever was coded in.
- **Ollama tool execution is sandboxed but not bulletproof.** The `safe_path()` and `is_blocked_command()` checks are good but haven't been formally audited.
- **Cost breaker thresholds are tuned for Claude pricing.** If you're using Ollama or other providers, the defaults might not make sense.
- **Early termination at 10 turns of reading can kill legitimate complex analysis tasks.** Some tasks genuinely need more exploration time.
- **Self-improvement (ForgeSmith/GEPA/SIMBA) needs 20-30 completed tasks before patterns emerge.** Don't expect magic after 5 runs.
- **Git worktree merges occasionally need manual intervention.** The automation handles the happy path but complex merge conflicts still need a human.
- **Agents still get stuck on complex tasks.** Analysis paralysis is real — sometimes an agent will spend all its turns reading code and never write anything.
---

## Related Documentation

- [Readme](README.md)
- [Architecture](ARCHITECTURE.md)
- [Deployment](DEPLOYMENT.md)
- [Contributing](CONTRIBUTING.md)
