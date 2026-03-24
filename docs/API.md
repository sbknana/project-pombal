# API.md — EQUIPA

## Table of Contents

- [API.md — EQUIPA](#apimd-equipa)
  - [Overview](#overview)
  - [CLI Interface](#cli-interface)
    - [Entry Point](#entry-point)
    - [Key CLI Capabilities (inferred)](#key-cli-capabilities-inferred)
  - [Core Modules](#core-modules)
    - [Database — `equipa/db.py`](#database-equipadbpy)
    - [Tasks — `equipa/tasks.py`](#tasks-equipataskspy)
    - [Dispatch — `equipa/dispatch.py`](#dispatch-equipadispatchpy)
    - [Agent Runner — `equipa/agent_runner.py`](#agent-runner-equipaagent_runnerpy)
    - [Lessons & Episodes — `equipa/lessons.py`](#lessons-episodes-equipalessonspy)
    - [Parsing — `equipa/parsing.py`](#parsing-equipaparsingpy)
    - [Monitoring — `equipa/monitoring.py`](#monitoring-equipamonitoringpy)
    - [Security — `equipa/security.py`](#security-equipasecuritypy)
    - [Git Operations — `equipa/git_ops.py`](#git-operations-equipagit_opspy)
    - [Preflight — `equipa/preflight.py`](#preflight-equipapreflightpy)
  - [Forgesmith — Self-Improvement Engine](#forgesmith-self-improvement-engine)
    - [Core — `forgesmith.py`](#core-forgesmithpy)
    - [SIMBA Rules — `forgesmith_simba.py`](#simba-rules-forgesmith_simbapy)
    - [GEPA — `forgesmith_gepa.py`](#gepa-forgesmith_gepapy)
    - [Impact Analysis — `forgesmith_impact.py`](#impact-analysis-forgesmith_impactpy)
  - [Ollama Agent — `ollama_agent.py`](#ollama-agent-ollama_agentpy)
    - [Sandboxed Tool Execution](#sandboxed-tool-execution)
  - [Rubric Quality Scoring — `rubric_quality_scorer.py`](#rubric-quality-scoring-rubric_quality_scorerpy)
    - [Scoring Dimensions (inferred)](#scoring-dimensions-inferred)
  - [Tools](#tools)
    - [Performance Analysis — `analyze_performance.py`](#performance-analysis-analyze_performancepy)
    - [Forge Dashboard — `tools/forge_dashboard.py`](#forge-dashboard-toolsforge_dashboardpy)
    - [Forge Arena — `tools/forge_arena.py`](#forge-arena-toolsforge_arenapy)
    - [Nightly Review — `nightly_review.py`](#nightly-review-nightly_reviewpy)
    - [Database Migration — `db_migrate.py`](#database-migration-db_migratepy)
    - [AutoResearch — `autoresearch_loop.py`](#autoresearch-autoresearch_looppy)
  - [SARIF Helpers — `skills/security/static-analysis/skills/sarif-parsing/resources/sarif_helpers.py`](#sarif-helpers-skillssecuritystatic-analysisskillssarif-parsingresourcessarif_helperspy)
  - [Error Handling](#error-handling)
    - [Error Classification](#error-classification)
    - [Loop Detection](#loop-detection)
    - [Cost Breakers](#cost-breakers)
  - [Lesson Sanitization — `lesson_sanitizer.py`](#lesson-sanitization-lesson_sanitizerpy)
  - [Adding HTTP API Endpoints](#adding-http-api-endpoints)
- [Example: Minimal FastAPI wrapper (not currently implemented)](#example-minimal-fastapi-wrapper-not-currently-implemented)
  - [Related Documentation](#related-documentation)

## Overview

EQUIPA is a **multi-agent AI orchestration platform** built in pure Python with zero pip dependencies. It uses SQLite as its data store and operates primarily through **CLI commands and internal function calls** rather than exposing traditional REST/GraphQL/tRPC API endpoints.

**There are no HTTP API endpoints detected in this project.**

EQUIPA's architecture is based on:
- CLI entry points (`equipa/cli.py`)
- Direct SQLite database operations (`equipa/db.py`)
- Agent dispatch via subprocess/async runners (`equipa/agent_runner.py`)
- Internal Python module interfaces

The sections below document the **programmatic interfaces** available for integration, organized by module.

---

## CLI Interface

The primary user-facing interface is the CLI defined in `equipa/cli.py`.

### Entry Point

```bash
python -m equipa.cli
```

The CLI calls `async_main()` internally, which handles argument parsing and dispatches work.

### Key CLI Capabilities (inferred)

| Command / Mode | Description |
|---|---|
| Auto-dispatch | Scans pending work, scores projects, and dispatches agents automatically |
| Parallel goals | Runs multiple goals concurrently from a goals file |
| Parallel tasks | Dispatches specific task IDs in parallel |
| Single task | Runs a single task by ID |

---

## Core Modules

### Database — `equipa/db.py`

All state is stored in SQLite (30+ table schema).

| Function | Description | Parameters |
|---|---|---|
| `get_db_connection(write)` | Returns a SQLite connection | `write: bool` — whether to open in write mode |
| `ensure_schema()` | Creates/verifies all required tables | None |
| `classify_error(error_text)` | Categorizes an error string into a known class | `error_text: str` — raw error output |

### Tasks — `equipa/tasks.py`

| Function | Description | Parameters | Returns |
|---|---|---|---|
| `fetch_task(task_id)` | Retrieves a single task by ID | `task_id: int` | Task dict (inferred) |
| `fetch_next_todo(project_id)` | Gets the next pending task for a project | `project_id: int` | Task dict or None (inferred) |
| `fetch_project_context(project_id)` | Returns context/state for a project | `project_id: int` | Context dict (inferred) |
| `fetch_project_info(project_id)` | Returns project metadata | `project_id: int` | Project dict (inferred) |
| `fetch_tasks_by_ids(task_ids)` | Bulk-fetches tasks | `task_ids: list[int]` | List of task dicts (inferred) |
| `get_task_complexity(task)` | Determines complexity rating of a task | `task: dict` | Complexity string/int (inferred) |
| `verify_task_updated(task_id)` | Confirms a task was modified in the DB | `task_id: int` | `bool` (inferred) |
| `resolve_project_dir(task)` | Determines the filesystem path for a task's project | `task: dict` | `str` — directory path (inferred) |

### Dispatch — `equipa/dispatch.py`

| Function | Description | Parameters |
|---|---|---|
| `load_dispatch_config(filepath)` | Loads dispatch configuration from a JSON/YAML file | `filepath: str` |
| `scan_pending_work()` | Queries DB for all actionable tasks | None |
| `score_project(summary, config)` | Scores a project for dispatch priority | `summary: dict`, `config: dict` |
| `apply_dispatch_filters(work, config, args)` | Filters work items based on config rules and CLI args | `work: list`, `config: dict`, `args` |
| `is_feature_enabled(dispatch_config, feature_name)` | Checks if a feature flag is enabled | `dispatch_config: dict`, `feature_name: str` |
| `run_auto_dispatch(scored, config, args)` | *(async)* Dispatches agents for scored work items | `scored: list`, `config: dict`, `args` |
| `load_goals_file(filepath)` | Loads a goals definition file | `filepath: str` |
| `validate_goals(goals)` | Validates goal structure | `goals: list` |
| `run_parallel_goals(resolved_goals, defaults, args)` | *(async)* Executes multiple goals concurrently | `resolved_goals: list`, `defaults: dict`, `args` |
| `parse_task_ids(task_str)` | Parses comma-separated task IDs | `task_str: str` |
| `run_parallel_tasks(task_ids, args)` | *(async)* Dispatches specific tasks in parallel | `task_ids: list[int]`, `args` |

### Agent Runner — `equipa/agent_runner.py`

| Function | Description | Parameters |
|---|---|---|
| `run_agent(cmd, timeout)` | *(async)* Executes an agent subprocess with a timeout | `cmd: str`, `timeout: int` |

### Lessons & Episodes — `equipa/lessons.py`

| Function | Description | Parameters |
|---|---|---|
| `update_lesson_injection_count(lesson_ids)` | Increments injection counter for used lessons | `lesson_ids: list[int]` |
| `get_active_simba_rules()` | Retrieves active SIMBA rules for injection | None |
| `update_episode_injection_count(episode_ids)` | Increments injection counter for used episodes | `episode_ids: list[int]` |

### Parsing — `equipa/parsing.py`

| Function | Description | Parameters | Returns |
|---|---|---|---|
| `estimate_tokens(text)` | Estimates token count for a text string | `text: str` | `int` (inferred) |
| `compute_keyword_overlap(text_a, text_b)` | Computes keyword similarity between two texts | `text_a: str`, `text_b: str` | `float` (inferred) |
| `deduplicate_lessons(lessons)` | Removes duplicate lessons by content similarity | `lessons: list` | `list` |
| `compact_agent_output(raw_output, max_words)` | Truncates/summarizes agent output | `raw_output: str`, `max_words: int` | `str` |
| `parse_reflection(result_text)` | Extracts reflection/learning from agent output | `result_text: str` | `dict` (inferred) |
| `parse_approach_summary(result_text)` | Extracts approach description from agent output | `result_text: str` | `str` (inferred) |
| `compute_initial_q_value(outcome)` | Computes Q-value for RL-style episode tracking | `outcome` | `float` (inferred) |
| `parse_tester_output(result_text)` | Parses tester agent structured output | `result_text: str` | `dict` (inferred) |
| `parse_developer_output(result_text)` | Parses developer agent structured output | `result_text: str` | `dict` (inferred) |
| `build_test_failure_context(test_results, cycle)` | Builds context for retry after test failure | `test_results: dict`, `cycle: int` | `str` (inferred) |
| `validate_output(result)` | Validates agent output structure | `result` | `bool` (inferred) |

### Monitoring — `equipa/monitoring.py`

#### `LoopDetector` class

Detects when agents are stuck in loops.

| Method | Description | Parameters |
|---|---|---|
| `_fingerprint(...)` | Creates a hash fingerprint of agent state | Internal |
| `_get_files_changed(...)` | Detects file changes between iterations | Internal |
| `record(...)` | Records an iteration for loop detection | Agent state data |
| `warning_message(...)` | Generates a warning message for near-loop states | None |
| `termination_summary(...)` | Generates termination explanation | None |

| Function | Description | Parameters |
|---|---|---|
| `calculate_dynamic_budget(max_turns)` | Computes dynamic budget thresholds for turn-based warnings | `max_turns: int` |

### Security — `equipa/security.py`

| Function | Description | Parameters | Returns |
|---|---|---|---|
| `wrap_untrusted(content, delimiter)` | Wraps untrusted content in safe delimiters | `content: str`, `delimiter: str` | `str` |
| `generate_skill_manifest()` | Generates SHA256 manifest of skill/prompt files | None | `dict` |
| `write_skill_manifest()` | Writes manifest to disk | None | None |
| `verify_skill_integrity()` | Verifies skill files against stored manifest | None | `bool` (inferred) |

### Git Operations — `equipa/git_ops.py`

| Function | Description | Parameters |
|---|---|---|
| `detect_project_language(project_dir)` | Detects programming languages and frameworks in a project | `project_dir: str` |
| `check_gh_installed()` | Checks if GitHub CLI is available | None |
| `setup_all_repos(args)` | Sets up/clones all project repositories | `args` |

### Preflight — `equipa/preflight.py`

| Function | Description | Parameters |
|---|---|---|
| `auto_install_dependencies(project_dir, output)` | *(async)* Detects and installs project dependencies before agent runs | `project_dir: str`, `output` |

---

## Forgesmith — Self-Improvement Engine

Forgesmith is EQUIPA's meta-learning system that analyzes agent performance and evolves prompts, configs, and rules.

### Core — `forgesmith.py`

```bash
python forgesmith.py [--dry-run] [--report] [--rollback RUN_ID] [--propose-only]
```

| Mode | Description |
|---|---|
| `--dry-run` | Analyze and propose changes without applying |
| `--report` | Generate performance report only |
| `--rollback RUN_ID` | Revert changes from a specific Forgesmith run |
| `--propose-only` | Generate OPRO proposals without applying |

#### Key Functions

| Function | Description | Parameters |
|---|---|---|
| `collect_agent_runs(cfg)` | Gathers recent agent run data | `cfg: dict` |
| `extract_lessons(runs, cfg)` | Extracts lessons from agent runs | `runs: list`, `cfg: dict` |
| `get_relevant_lessons(role, error_type, limit)` | Retrieves lessons filtered by role and error type | `role: str`, `error_type: str`, `limit: int` |
| `analyze_max_turns_hit(runs, cfg)` | Finds tasks that exhausted their turn budget | `runs: list`, `cfg: dict` |
| `analyze_repeat_errors(runs, cfg)` | Identifies recurring error patterns | `runs: list`, `cfg: dict` |
| `run_analysis(cfg)` | Runs all analysis passes | `cfg: dict` |
| `apply_changes(findings, run_id, cfg, dry_run)` | Applies recommended changes | `findings: list`, `run_id: str`, `cfg: dict`, `dry_run: bool` |
| `rollback_change(change)` | Reverts a single applied change | `change: dict` |
| `compute_rubric_score(run, cfg)` | Scores a run against quality rubric | `run: dict`, `cfg: dict` |
| `evolve_rubric_weights(cfg)` | Evolves rubric scoring weights based on outcomes | `cfg: dict` |
| `generate_opro_proposals(runs, cfg, dry_run)` | Generates prompt optimization proposals via OPRO | `runs: list`, `cfg: dict`, `dry_run: bool` |

### SIMBA Rules — `forgesmith_simba.py`

Self-Improving Meta-Behavioral Adaptation. Generates targeted rules from success/failure patterns.

```bash
python forgesmith_simba.py [--dry-run] [--role ROLE]
```

| Function | Description | Parameters |
|---|---|---|
| `find_high_variance_episodes(lookback_days)` | Finds episodes with inconsistent outcomes | `lookback_days: int` |
| `find_hardest_cases(lookback_days)` | Identifies consistently failing task types | `lookback_days: int` |
| `build_simba_prompt(role, successes, failures, hardest_cases, existing_rules)` | Constructs LLM prompt for rule generation | Multiple |
| `validate_rule(rule, existing_rules)` | Validates a proposed rule against constraints | `rule: dict`, `existing_rules: list` |
| `store_rules(role, rules, dry_run)` | Persists validated rules to DB | `role: str`, `rules: list`, `dry_run: bool` |
| `evaluate_simba_rules()` | Evaluates rule effectiveness | None |
| `prune_stale_rules(dry_run)` | Removes ineffective rules | `dry_run: bool` |

### GEPA — `forgesmith_gepa.py`

Guided Evolutionary Prompt Adaptation. Evolves system prompts using DSPy-style optimization.

```bash
python forgesmith_gepa.py [--dry-run] [--role ROLE]
```

| Function | Description | Parameters |
|---|---|---|
| `collect_episodes_for_role(role, lookback_days)` | Gathers training episodes for a role | `role: str`, `lookback_days: int` |
| `validate_evolved_prompt(current_prompt, evolved_prompt)` | Validates a proposed prompt evolution | `current_prompt: str`, `evolved_prompt: str` |
| `get_ab_prompt_for_role(role)` | Gets the A/B test variant prompt | `role: str` |
| `rollback_evolved_prompt(role, version)` | Reverts to a previous prompt version | `role: str`, `version: int` |
| `get_ab_test_status(role)` | Returns current A/B test status for a role | `role: str` |

### Impact Analysis — `forgesmith_impact.py`

| Function | Description | Parameters |
|---|---|---|
| `identify_affected_roles(change_type, target_file, old_value, new_value)` | Determines which roles are affected by a change | Multiple |
| `compute_blast_radius(affected_roles)` | Estimates the scope of a change's impact | `affected_roles: list` |
| `assess_risk_level(change_type, affected_roles, blast_radius, diff_ratio)` | Assigns risk level to a proposed change | Multiple |

---

## Ollama Agent — `ollama_agent.py`

Local LLM agent interface for running tasks via Ollama.

| Function | Description | Parameters |
|---|---|---|
| `ollama_chat(base_url, model, messages, tools, timeout)` | Sends a chat request to Ollama API | `base_url: str`, `model: str`, `messages: list`, `tools: list`, `timeout: int` |
| `check_ollama_health(base_url)` | Health check for Ollama server | `base_url: str` |
| `list_ollama_models(base_url)` | Lists available Ollama models | `base_url: str` |

### Sandboxed Tool Execution

| Function | Description | Parameters |
|---|---|---|
| `safe_path(project_dir, relative_path)` | Validates and resolves a path within the project sandbox | `project_dir: str`, `relative_path: str` |
| `is_safe_read_command(command)` | Checks if a shell command is read-only | `command: str` |
| `is_blocked_command(command)` | Checks if a shell command is forbidden | `command: str` |
| `exec_read_file(project_dir, args)` | Reads a file within the sandbox | `project_dir: str`, `args: dict` |
| `exec_list_directory(project_dir, args)` | Lists directory contents within the sandbox | `project_dir: str`, `args: dict` |
| `exec_search_files(project_dir, args)` | Searches for files by pattern | `project_dir: str`, `args: dict` |
| `exec_grep(project_dir, args)` | Greps file contents | `project_dir: str`, `args: dict` |
| `exec_bash(project_dir, args, allow_write)` | Executes a bash command (sandboxed) | `project_dir: str`, `args: dict`, `allow_write: bool` |
| `exec_write_file(project_dir, args)` | Writes a file within the sandbox | `project_dir: str`, `args: dict` |
| `exec_edit_file(project_dir, args)` | Edits a file within the sandbox | `project_dir: str`, `args: dict` |

---

## Rubric Quality Scoring — `rubric_quality_scorer.py`

| Function | Description | Parameters | Returns |
|---|---|---|---|
| `score_agent_output(result_text, files_changed, role)` | Scores agent output across 5 quality dimensions | `result_text: str`, `files_changed: list`, `role: str` | `dict` with `dimensions`, `total`, `normalized`, `details` (inferred) |

### Scoring Dimensions (inferred)

| Dimension | Description |
|---|---|
| Naming consistency | Quality of identifiers and naming conventions |
| Code structure | Organization and architecture quality |
| Test coverage | Presence and quality of tests |
| Documentation | Inline and external documentation |
| Error handling | Robustness of error handling patterns |

---

## Tools

### Performance Analysis — `analyze_performance.py`

```bash
python analyze_performance.py [--project PROJECT_ID] [--days N]
```

Generates comprehensive performance reports from task history and checkpoint data.

### Forge Dashboard — `tools/forge_dashboard.py`

```bash
python tools/forge_dashboard.py
```

Terminal dashboard showing task summaries, throughput, blocked tasks, and session activity.

### Forge Arena — `tools/forge_arena.py`

```bash
python tools/forge_arena.py [--dry-run]
```

Automated testing arena that creates tasks, dispatches agents, checks convergence, and exports LoRA training data.

### Nightly Review — `nightly_review.py`

```bash
python nightly_review.py [--db PATH]
```

Generates a nightly portfolio review including accomplishments, blockers, stale projects, agent stats, and upcoming reminders.

### Database Migration — `db_migrate.py`

```bash
python db_migrate.py [--db PATH]
```

Runs incremental schema migrations (v0 → v1 → v2 → v3 → v4) with automatic backup.

### AutoResearch — `autoresearch_loop.py`

```bash
python autoresearch_loop.py [--role ROLE] [--target PCT] [--max-rounds N] [--status]
```

Automated prompt optimization loop: mutate → deploy → test → evaluate → iterate.

---

## SARIF Helpers — `skills/security/static-analysis/skills/sarif-parsing/resources/sarif_helpers.py`

Utility library for parsing SARIF (Static Analysis Results Interchange Format) files.

| Function | Description | Parameters | Returns |
|---|---|---|---|
| `load_sarif(path)` | Loads a SARIF file | `path: str` | `dict` |
| `save_sarif(sarif, path, indent)` | Writes SARIF to disk | `sarif: dict`, `path: str`, `indent: int` | None |
| `extract_findings(sarif)` | Extracts all findings from SARIF data | `sarif: dict` | `list[Finding]` |
| `filter_by_level(findings, *levels)` | Filters findings by severity level | `findings: list`, `*levels: str` | `list[Finding]` |
| `filter_by_file(findings, pattern)` | Filters findings by file path pattern | `findings: list`, `pattern: str` | `list[Finding]` |
| `filter_by_rule(findings, *rule_ids)` | Filters findings by rule ID | `findings: list`, `*rule_ids: str` | `list[Finding]` |
| `group_by_file(findings)` | Groups findings by source file | `findings: list` | `dict` |
| `group_by_rule(findings)` | Groups findings by rule ID | `findings: list` | `dict` |
| `deduplicate(findings)` | Removes duplicate findings | `findings: list` | `list[Finding]` |
| `merge_sarif_files(*paths)` | Merges multiple SARIF files | `*paths: str` | `dict` |
| `summary(findings)` | Generates a human-readable summary | `findings: list` | `str` (inferred) |

---

## Error Handling

### Error Classification

EQUIPA classifies errors into known categories via `classify_error()`:

| Error Class | Detection Pattern (inferred) |
|---|---|
| `timeout` | Process timeout exceeded |
| `file_not_found` | File/path not found errors |
| `permission` | Permission denied errors |
| `syntax` | Syntax errors in code |
| `import` | Import/module not found errors |
| `test_failure` | Test assertion failures |
| `unknown` | Unclassified errors |

### Loop Detection

The `LoopDetector` class prevents agents from spinning indefinitely:

| Threshold | Behavior |
|---|---|
| Warning threshold (configurable) | Injects a warning message into agent context |
| Termination threshold (configurable) | Kills the agent and records termination |

Loop detection monitors:
- Repeated identical fingerprints (same output hash)
- Alternating patterns (A→B→A→B cycles)
- Monologue detection (consecutive text-only responses without tool use)
- Tool call loops (same tool called repeatedly with same args)

### Cost Breakers

Tasks are terminated if estimated cost exceeds configured limits. Cost limits scale with task complexity (inferred).

---

## Lesson Sanitization — `lesson_sanitizer.py`

Security layer for injected lesson content:

| Threat | Mitigation |
|---|---|
| XML injection tags | Stripped |
| Role override phrases | Stripped |
| Base64 payloads | Stripped |
| ANSI escape sequences | Stripped |
| Dangerous code blocks | Stripped |
| Excessive length | Capped to max length |

---

## Adding HTTP API Endpoints

EQUIPA currently operates as a CLI tool with direct database access. To expose an HTTP API, consider:

1. **FastAPI wrapper** — Add a `equipa/api.py` using FastAPI (would require adding a dependency) to expose task management, dispatch, and monitoring endpoints
2. **MCP Server** — The project references MCP config generation (`step_generate_mcp_config`), suggesting Model Context Protocol integration is supported
3. **SQLite over HTTP** — Use a tool like `datasette` to expose read-only database queries

```python
# Example: Minimal FastAPI wrapper (not currently implemented)
from fastapi import FastAPI
from equipa.tasks import fetch_task, fetch_next_todo
from equipa.dispatch import scan_pending_work

app = FastAPI()

@app.get("/tasks/{task_id}")
def get_task(task_id: int):
    return fetch_task(task_id)

@app.get("/projects/{project_id}/next")
def next_task(project_id: int):
    return fetch_next_todo(project_id)

@app.get("/dispatch/pending")
def pending_work():
    return scan_pending_work()
```
---

## Related Documentation

- [Architecture](ARCHITECTURE.md)
- [Deployment](DEPLOYMENT.md)
- [Contributing](CONTRIBUTING.md)
