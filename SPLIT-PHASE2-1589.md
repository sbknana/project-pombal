# Phase 2: Monolith Split — Extract Low-Coupling Modules

**Task:** #1589
**Date:** 2026-03-23
**Status:** Complete

## Summary

Completed Phase 2 of the Strangler Fig migration by extracting 4 low-coupling modules from `forge_orchestrator.py` into the `equipa/` package. A previous agent created the module files and added imports; this session removed all duplicate function definitions from the monolith and moved one additional function (`print_dispatch_plan`). All 331 tests pass with zero changes.

## Modules Extracted

### 1. `equipa/output.py` (291 lines, Layer 1)
Pure output functions with no dependencies beyond constants:
- `log()` — buffered/immediate print
- `print_manager_summary()` — Manager mode run summary
- `_print_task_summary()` — internal formatted agent run summary
- `print_summary()` — single agent run summary
- `print_dev_test_summary()` — dev-test loop summary
- `_print_batch_summary()` — shared batch summary logic
- `print_parallel_summary()` — parallel goals summary table
- `print_dispatch_summary()` — auto-dispatch results report
- `print_dispatch_plan()` — dispatch plan preview (moved in this session)

Dependencies: `equipa.constants` (MAX_DEV_TEST_CYCLES, NO_PROGRESS_LIMIT, DEFAULT_MODEL, DEFAULT_MAX_TURNS, PROJECT_DIRS), `equipa.monitoring.calculate_dynamic_budget` (lazy import in print_dispatch_plan).

### 2. `equipa/messages.py` (131 lines, Layer 3)
Inter-agent messaging via TheForge DB:
- `post_agent_message()` — insert message from one agent role to another
- `read_agent_messages()` — fetch unread messages for a role
- `mark_messages_read()` — mark messages consumed by cycle
- `format_messages_for_prompt()` — format messages for agent prompt with untrusted content markers

Dependencies: Late imports from `forge_orchestrator` for DB functions (`get_db_connection`, `ensure_schema`, `_make_untrusted_delimiter`, `wrap_untrusted`). These will be resolved when the DB layer is extracted in Phase 3.

### 3. `equipa/parsing.py` (571 lines, Layer 4)
All output parsing, text extraction, and structured data processing:
- Constants: `CHARS_PER_TOKEN`, `SYSTEM_PROMPT_TOKEN_TARGET`, `SYSTEM_PROMPT_TOKEN_HARD_LIMIT`, `EPISODE_REDUCTION_THRESHOLD`
- Schemas: `_TESTER_SCHEMA`, `_DEVELOPER_FILES_SCHEMA`, `_FAILURE_KEYWORD_PATTERNS`, `_FAILURE_PRIORITY`
- Text extraction: `_extract_marker_value()`, `_extract_section()`, `_trim_prompt_section()`
- Output parsing: `_parse_structured_output()`, `parse_tester_output()`, `parse_developer_output()`, `parse_reflection()`, `parse_approach_summary()`, `parse_error_patterns()`, `validate_output()`
- Token/text utilities: `estimate_tokens()`, `compact_agent_output()`, `compute_keyword_overlap()`, `deduplicate_lessons()`
- Quality scoring: `classify_agent_failure()`, `compute_initial_q_value()`
- Compaction: `build_compaction_summary()`, `build_test_failure_context()`

Dependencies: `equipa.constants` (EARLY_TERM_STUCK_PHRASES and related constants).

### 4. `equipa/monitoring.py` (689 lines, Layer 6)
Loop detection, budget management, and streaming check functions:
- Constants: `LOOP_WARNING_THRESHOLD`, `LOOP_TERMINATE_THRESHOLD`, `_TOOL_SIG_KEY`
- Class: `LoopDetector` — full loop detection state machine with output hash tracking, alternating pattern detection, and tool signature analysis
- Check functions: `_check_stuck_phrases()`, `_check_monologue()`, `_check_cost_limit()`, `_check_git_changes()`, `_parse_early_complete()`
- Tool analysis: `_build_tool_signature()`, `_detect_tool_loop()`, `_compute_output_hash()`
- Budget: `calculate_dynamic_budget()`, `adjust_dynamic_budget()`, `_get_budget_message()`
- Streaming: `_build_streaming_result()`

Dependencies: `equipa.constants` (EARLY_TERM_*, MONOLOGUE_*, BUDGET_*, COST_LIMITS, etc.), `equipa.parsing` (estimate_tokens).

### 5. `equipa/__init__.py` (276 lines)
Updated re-exports for all Phase 2 symbols plus the Phase 1 modules.

## Architecture Decisions

1. **Late import for `calculate_dynamic_budget` in `print_dispatch_plan`:** Since output.py is Layer 1 and monitoring.py is Layer 6, we use a late import inside the function body to avoid circular imports. This function is called only during `--auto-run --dry-run` so the lazy import has negligible cost.

2. **Messages uses late imports from monolith:** The `post_agent_message`, `read_agent_messages`, and `mark_messages_read` functions import `get_db_connection` and `ensure_schema` at call time. `format_messages_for_prompt` imports `_make_untrusted_delimiter` and `wrap_untrusted`. These late imports will be resolved when Phase 3 extracts the DB layer.

3. **`_extract_security_findings` stays in monolith:** This function at line ~3380 is NOT a parsing function — it's part of the security review scoring pipeline with deep DB dependencies. It correctly remains in the monolith.

4. **Duplicate definitions removed, not just shadowed:** A previous agent created the module files and added imports to the monolith, but left the old function definitions in place (shadowing the imports). This session removed ~120 lines of duplicate output functions, completing the extraction.

## Test Results

```
331 passed, 1 warning in 4.01s
```

All 331 existing tests pass without modification. The 1 warning is a pre-existing `DeprecationWarning` for `asyncio.get_event_loop()`.

## Lines Removed from Monolith

Output functions removed: ~120 lines (3 blocks of duplicate defs)
Previous session (Phase 2 creation): ~1340 lines (parsing, monitoring, messages)
Total Phase 2 net reduction: ~1460 lines from `forge_orchestrator.py`

## Monolith Status

| Metric | Before Phase 1 | After Phase 1 | After Phase 2 |
|--------|----------------|---------------|---------------|
| Monolith lines | ~6,000 | ~5,555 | 5,466 |
| `equipa/` modules | 0 | 4 (constants, checkpoints, git_ops, __init__) | 8 (+output, messages, parsing, monitoring) |
| Extracted functions | 0 | ~25 | ~65 |

## Dependency Hierarchy

```
L1: constants.py (no deps)
L1: checkpoints.py (constants)
L1: output.py (constants, lazy: monitoring)
L2: git_ops.py (constants, lazy: monolith)
L3: messages.py (lazy: monolith DB functions)
L4: parsing.py (constants)
L6: monitoring.py (constants, parsing)
```

No circular imports exist. All cross-layer references use late imports.

## Next Steps

- Task #1590: Extract DB layer (get_db_connection, ensure_schema, all DB functions)
- Task #1591: Extract core engine (run_agent, dev_test_loop, manager_loop)
- Task #1592: Entry points + final shim
