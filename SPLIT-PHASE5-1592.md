# EQUIPA Monolith Split — Phase 5: Entry Points & Shim (Task #1592)

## Summary

Final phase of the 5-phase monolith split. Extracted the last ~1000 lines of
`forge_orchestrator.py` (dispatch/auto-run logic and CLI entry points) into
`equipa/dispatch.py` and `equipa/cli.py`, then converted the monolith into a
26-line backward-compatibility shim.

Additionally cleaned up all 8 remaining `from forge_orchestrator import` late
imports across the equipa package, replacing them with direct submodule imports.

## Before

- `forge_orchestrator.py`: 2,072 lines (down from ~5,000 at Phase 0)
- 8 late imports from `forge_orchestrator` inside equipa/ submodules

## After

- `forge_orchestrator.py`: **26-line shim** (`from equipa import *; from equipa.cli import main, async_main`)
- `equipa/` package: **20 modules** (18 implementation + `__init__.py` + `__pycache__/`)
- **Zero** `from forge_orchestrator import` in equipa/ package
- **331 tests pass** (0 failures, 1 deprecation warning)

## New Modules (Phase 5)

| Module | Lines | Contents |
|--------|------:|---------|
| `equipa/dispatch.py` | 980 | `scan_pending_work`, `score_project`, `apply_dispatch_filters`, `run_project_tasks`, `run_project_dispatch`, `run_auto_dispatch`, `run_parallel_tasks`, `run_single_goal`, `run_parallel_goals`, `parse_task_ids`, `load_goals_file`, `validate_goals`, `load_dispatch_config`, `is_feature_enabled`, `DEFAULT_DISPATCH_CONFIG`, `DEFAULT_FEATURE_FLAGS` |
| `equipa/cli.py` | 755 | `async_main`, `main`, `load_config`, `get_provider`, `get_ollama_model`, `get_ollama_base_url`, `_handle_add_project`, `_post_task_telemetry` |

## Complete Module Inventory (equipa/)

| Module | Lines | Phase | Responsibility |
|--------|------:|-------|---------------|
| `constants.py` | 208 | 1 | All configuration constants |
| `checkpoints.py` | 82 | 1 | Checkpoint save/load/clear |
| `git_ops.py` | 367 | 1 | Git operations, repo setup |
| `output.py` | 291 | 2 | Logging, summary printing |
| `messages.py` | 129 | 2 | Inter-agent messaging |
| `parsing.py` | 571 | 2 | Agent output parsing, compaction |
| `monitoring.py` | 689 | 2 | Loop detection, early termination |
| `db.py` | 414 | 3 | Database operations, schema |
| `tasks.py` | 272 | 3 | Task fetching, resolution |
| `lessons.py` | 461 | 3 | Lesson/episode injection |
| `roles.py` | 164 | 3 | Role discovery, model/turns config |
| `security.py` | 120 | 4 | Skill integrity, content isolation |
| `prompts.py` | 493 | 4 | System prompt building |
| `reflexion.py` | 143 | 4 | Post-task self-reflection |
| `agent_runner.py` | 661 | 4 | Agent CLI command building, execution |
| `preflight.py` | 306 | 4 | Build checks, dependency install |
| `loops.py` | 750 | 4 | Dev-test loop, security review |
| `manager.py` | 309 | 4 | Manager/planner/evaluator loops |
| `dispatch.py` | 980 | 5 | Auto-run, goals, parallel dispatch |
| `cli.py` | 755 | 5 | CLI entry points, arg parsing |
| `__init__.py` | 526 | 1-5 | Re-exports all public symbols |

**Total equipa/ package: 8,191 lines** (excluding `__init__.py` re-exports)

## Late Import Cleanup

Replaced 8 `from forge_orchestrator import` statements in equipa/ with direct submodule imports:

| File | Old Import | New Import |
|------|-----------|------------|
| `lessons.py` (×2) | `forge_orchestrator.{sanitize_*, wrap_untrusted}` | `lesson_sanitizer.*`, `equipa.security.wrap_untrusted` |
| `git_ops.py` | `forge_orchestrator.fetch_project_info` | `equipa.tasks.fetch_project_info` |
| `messages.py` | `forge_orchestrator.{_make_untrusted_delimiter, wrap_untrusted}` | `equipa.security.*` |
| `db.py` | `forge_orchestrator._last_prompt_version` | `equipa.prompts._last_prompt_version` |
| `agent_runner.py` | `forge_orchestrator.{get_provider, get_ollama_*}` | `equipa.cli.*` |
| `prompts.py` | `forge_orchestrator.is_feature_enabled` | `equipa.dispatch.is_feature_enabled` |
| `loops.py` (×3) | `forge_orchestrator.{is_feature_enabled, load_dispatch_config}` | `equipa.dispatch.*` |

## Backward Compatibility

The shim in `forge_orchestrator.py` ensures:
- `python forge_orchestrator.py --task 63` still works
- All existing test imports (`from forge_orchestrator import X`) still work
- `if __name__ == "__main__": main()` entry point preserved

## Verification

```
$ python3 -m pytest -x -q
331 passed, 1 warning in 7.53s
```

## Commits

1. `e598fe6` — Phase 5 extraction: dispatch.py, cli.py, shim, __init__.py
2. `b18024f` — Fix all 8 late imports from forge_orchestrator to equipa submodules
