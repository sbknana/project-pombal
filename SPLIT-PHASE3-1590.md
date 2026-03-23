# Phase 3: Database Layer Extraction — Task #1590

## Summary

Extracted the database layer from `forge_orchestrator.py` into five focused modules
under `equipa/`. Fixed 12 test failures caused by stale mock patch targets that
still referenced the monolith instead of the new `equipa.db` module.

## Modules Extracted

### equipa/db.py (414 lines) — Layer 2
Imports only from `equipa.constants`. All other DB-dependent modules import from here.

| Function | Lines | Description |
|----------|-------|-------------|
| `get_db_connection()` | 22–37 | Open read-only or read-write SQLite connection |
| `ensure_schema()` | 45–168 | Idempotent table/index creation for agent tables |
| `record_agent_run()` | 173–253 | Insert agent run telemetry record |
| `_get_latest_agent_run_id()` | 256–270 | Fetch most recent run ID for a task |
| `classify_error()` | 275–296 | Categorize error strings into types |
| `log_agent_action()` | 299–333 | Insert single agent action record |
| `bulk_log_agent_actions()` | 336–371 | Batch insert agent actions in one transaction |
| `update_task_status()` | 376–414 | Map outcomes to task statuses in TheForge |

### equipa/tasks.py (272 lines) — Layer 2
Imports from `equipa.constants` and `equipa.db`.

| Function | Lines | Description |
|----------|-------|-------------|
| `fetch_task()` | 24–39 | Fetch task by ID with project info |
| `fetch_next_todo()` | 43–72 | Find highest-priority todo for a project |
| `fetch_project_context()` | 75–120 | Get session notes, questions, decisions |
| `_get_task_status()` | 123–133 | Quick status read |
| `fetch_project_info()` | 136–151 | Get project name/codename |
| `fetch_tasks_by_ids()` | 154–181 | Batch fetch tasks preserving order |
| `get_task_complexity()` | 184–207 | Resolve complexity from DB or description length |
| `verify_task_updated()` | 210–232 | Check if agent updated task status |
| `resolve_project_dir()` | 235–272 | Find project directory from config or DB |

### equipa/lessons.py (452 lines) — Layer 3
Imports from `equipa.constants`, `equipa.db`, `equipa.parsing`. Uses late imports
for sanitizer functions still in the monolith.

| Function | Lines | Description |
|----------|-------|-------------|
| `format_lessons_for_injection()` | 32–92 | Format+sanitize lessons for agent prompts |
| `update_lesson_injection_count()` | 95–116 | Increment lesson injection counter |
| `_injected_episodes_by_task` | 123 | Module-level tracker dict |
| `get_relevant_episodes()` | 126–239 | Fetch+rank episodes by q-value and relevance |
| `format_episodes_for_injection()` | 242–287 | Format episodes for prompt injection |
| `record_agent_episode()` | 290–358 | Store Reflexion episode with q-value |
| `update_episode_injection_count()` | 363–384 | Increment episode injection counter |
| `update_episode_q_values()` | 387–424 | Apply MemRL reward signal to q-values |
| `update_injected_episode_q_values_for_task()` | 427–452 | Post-task q-value update |

### equipa/roles.py (164 lines) — Layer 2
Imports from `equipa.constants`. Does not depend on `equipa.db`.

| Function | Lines | Description |
|----------|-------|-------------|
| `get_role_turns()` | 25–64 | Resolve max turns per role with complexity multiplier |
| `get_role_model()` | 67–109 | Resolve model per role/complexity/config |
| `_discover_roles()` | 112–131 | Dynamically build ROLE_PROMPTS from .md files |
| `_accumulate_cost()` | 133–153 | Extract or estimate cost from agent result |
| `_apply_cost_totals()` | 156–164 | Stamp cost/duration onto result dict |

### Budget functions — already in equipa/monitoring.py (Phase 2)
The task description listed `budget.py` (~80 lines) with `calculate_dynamic_budget`,
`adjust_dynamic_budget`, `_check_cost_limit`. These were already extracted to
`equipa/monitoring.py` in Phase 2 since they are tightly coupled with the loop
detection and cost monitoring logic. No separate `budget.py` was needed.

## Re-exports

All public symbols are re-exported from `equipa/__init__.py` (359 lines) and from
`forge_orchestrator.py` via `from equipa.db import ...` etc., ensuring full backward
compatibility for callers that import from either location.

## Test Fixes

12 tests in 2 files failed because mock patches targeted the monolith's namespace
(`forge_orchestrator.get_db_connection`, `forge_orchestrator._SCHEMA_ENSURED`) instead
of the canonical module (`equipa.db.get_db_connection`, `equipa.db._SCHEMA_ENSURED`).

| File | Tests Fixed | Change |
|------|-------------|--------|
| `tests/test_agent_actions.py` | 3 (ensure_schema, log_agent_action, bulk_log) | Patch target → `equipa.db.*` |
| `tests/test_agent_messages.py` | 12 (all DB-touching tests) | Patch `equipa.constants.THEFORGE_DB` + `equipa.db._SCHEMA_ENSURED` in setup/teardown |

## Test Results

**331 tests passed, 0 failures, 1 warning** (asyncio deprecation in preflight test).

## Monolith Size Reduction

| Metric | Before Phase 1 | After Phase 3 |
|--------|----------------|---------------|
| `forge_orchestrator.py` | ~5000 lines | 4462 lines |
| `equipa/` package total | 0 lines | 3998 lines |
| Modules extracted | 0 | 12 |

## Layer Dependency Map

```
Layer 1 (leaf):     constants, checkpoints, git_ops
Layer 2 (config):   db, tasks, roles, output
Layer 3 (logic):    parsing, monitoring, lessons, messages
Monolith (L4):      forge_orchestrator.py (orchestration, prompt building, agent dispatch)
```

## Remaining Late Imports

`lessons.py` and `messages.py` still use late imports from `forge_orchestrator` for:
- `sanitize_lesson_content`, `sanitize_error_signature`, `wrap_lessons_in_task_input`
- `wrap_untrusted`, `_make_untrusted_delimiter`

These will be extracted in Phase 4 (core engine extraction, Task #1591).
