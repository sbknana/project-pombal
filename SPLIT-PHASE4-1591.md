# Phase 4: Core Engine Extraction — SPLIT-PHASE4-1591

**Task:** #1591 — Phase 4: Monolith split — extract core engine
**Date:** 2026-03-23
**Status:** COMPLETE — 331 tests passing

## Summary

Extracted 7 core engine modules from `forge_orchestrator.py` into the `equipa/` package.
This is the riskiest phase — agent_runner, loops, and manager are the most interconnected
modules in the orchestrator. All 21 extracted functions were removed from the monolith and
replaced with imports from the new modules.

**Monolith reduction:** 4462 → 2072 lines (−2390 lines, −54%)
**equipa/ package:** 3998 → 6908 lines across 19 modules (+2910 lines, 7 new modules)

## Modules Extracted

| Module | Layer | Lines | Functions | Description |
|--------|-------|-------|-----------|-------------|
| `security.py` | L5 | 120 | 5 | Untrusted content isolation, skill integrity verification |
| `prompts.py` | L5 | 502 | 6 | System/task/planner/evaluator prompt construction |
| `reflexion.py` | L5 | 143 | 4 | Post-task self-reflection for RL learning |
| `agent_runner.py` | L6 | 661 | 5 | Agent dispatch, streaming, retry logic |
| `preflight.py` | L7 | 306 | 6 | Dependency installation, build checks, auto-fix |
| `loops.py` | L7 | 761 | 5 | Dev-test loop, quality scoring, security review |
| `manager.py` | L7 | 309 | 5 | Manager loop: Plan → Execute → Evaluate → Repeat |
| **Total** | | **2802** | **36** | |

## Dependency Layer Map (L1–L7)

```
L1: constants, checkpoints, git_ops           (leaf — no equipa imports)
L2: db, tasks, roles, output                  (import L1)
L3: parsing, monitoring, lessons, messages     (import L1–L2)
L5: security, prompts, reflexion              (import L1–L3 + late imports)
L6: agent_runner                               (import L1–L5 + late imports)
L7: preflight, loops, manager                  (import L1–L6 + late imports)
```

## Late Imports (Circular Dependency Avoidance)

These functions remain in the monolith (Phase 5 entry points) and are imported lazily:

| Module | Late Import | Source |
|--------|-------------|--------|
| `prompts.py` | `is_feature_enabled` | `forge_orchestrator` (with fallback) |
| `prompts.py` | `get_relevant_lessons` | `forgesmith` (with fallback) |
| `loops.py` | `is_feature_enabled` | `forge_orchestrator` (with fallback) |
| `loops.py` | `load_dispatch_config` | `forge_orchestrator` |
| `loops.py` | `sanitize_lesson_content`, `validate_lesson_structure` | `lesson_sanitizer` (with fallback) |
| `agent_runner.py` | `get_provider`, `get_ollama_model`, `get_ollama_base_url` | `forge_orchestrator` |
| `reflexion.py` | `run_agent` | `equipa.agent_runner` (avoids circular at import time) |
| `preflight.py` | `build_cli_command`, `dispatch_agent` | `equipa.agent_runner` |
| `preflight.py` | `build_system_prompt` | `equipa.prompts` |
| `preflight.py` | `get_role_model` | `equipa.roles` |

## Bugs Fixed During Extraction

1. **`build_planner_prompt` indentation bug** — `lines.append("## Open Questions")` was outside
   the `if questions:` block in the original monolith. Fixed in `equipa/prompts.py`.

2. **`build_system_prompt` episode injection bug** — Line 926 in original assigned to `episodes`
   instead of `prompt` when appending episode text. Fixed in `equipa/prompts.py`.

## Test Changes

- `test_task_type_routing.py::test_orchestrator_injection_logic` — Updated to check
  `equipa/prompts.py` instead of monolith for `task_type_prompts` patterns (code was extracted).

## What Remains in the Monolith (Phase 5)

The monolith (2072 lines) now contains only entry-point and configuration code:
- CLI argument parsing (`argparse`)
- Provider resolution (`get_provider`, `get_ollama_model`, `get_ollama_base_url`)
- Config loading (`load_config`, `load_dispatch_config`, `load_goals_file`)
- Feature flags (`is_feature_enabled`, `DEFAULT_FEATURE_FLAGS`)
- Dispatch filtering (`apply_dispatch_filters`, `DEFAULT_DISPATCH_CONFIG`)
- Entry-point orchestration (`run_project_tasks`, `run_project_dispatch`, `run_auto_dispatch`)
- Parallel/goal modes (`run_single_goal`, `run_parallel_goals`, `run_parallel_tasks`)
- Project management (`_handle_add_project`, `scan_pending_work`, `score_project`)
- Main functions (`async_main`, `main`)

## Cumulative Split Progress

| Phase | Task | Modules | Lines Extracted | Monolith After |
|-------|------|---------|-----------------|----------------|
| Phase 1 | #1588 | 3 (constants, checkpoints, git_ops) | 657 | ~4800 |
| Phase 2 | #1589 | 4 (output, messages, parsing, monitoring) | 1681 | ~4600 |
| Phase 3 | #1590 | 5 (db, tasks, lessons, roles, __init__) | 1660 | 4462 |
| **Phase 4** | **#1591** | **7 (security, prompts, reflexion, agent_runner, preflight, loops, manager)** | **2802** | **2072** |
| **Total** | | **19 modules** | **6908 lines** | **2072 lines** |
