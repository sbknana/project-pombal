# Changelog

All notable changes to ForgeTeam / Itzamna are documented here.

## [3.0.0] - 2026-03-04

### Added

- **Local LLM support via Ollama.** Run read-only agents (planner, evaluator, code-reviewer, security-reviewer, researcher) on local models. Zero API cost for review roles. (`ollama_agent.py`)
- **Provider abstraction.** Per-role provider selection in `dispatch_config.json`. Global `--provider` CLI flag for override. Supports `claude` and `ollama` providers.
- **Inter-agent messaging.** Agents post structured messages to each other across dev-test cycles via `agent_messages` table. Tester posts test results back to Developer. Developer reads messages at cycle start.
- **Per-tool action logging.** Every tool call logged to `agent_actions` table with input hashes (SHA256), output sizes, error classification, and duration. ForgeSmith uses this for fine-grained analysis.
- **Forge Arena** (`forge_arena.py`) — Automated agent evaluation and training data generation.
- **Forge Dashboard** (`forge_dashboard.py`) — Terminal-based performance dashboard.
- **Performance Analyzer** (`analyze_performance.py`) — Historical agent performance analysis.
- **ForgeSmith Backfill** (`forgesmith_backfill.py`) — Backfill scoring data from historical logs.
- **Training Data Preparation** (`prepare_training_data.py`) — Convert arena results to fine-tuning format.
- **QLoRA Training** (`train_qlora.py`, `train_qlora_peft.py`) — Fine-tune local models on ForgeTeam data.
- **Coordinator Mode documentation** (`docs/COORDINATOR.md`) — Guide for using Claude Code as a natural language coordinator.
- **Local LLM documentation** (`docs/LOCAL_LLM.md`) — Complete Ollama setup and configuration guide.
- **Training documentation** (`docs/TRAINING.md`) — Fine-tuning your own ForgeTeam model.
- **10 new test files** covering agent actions, agent messages, early termination, episode injection, lessons injection, loop detection, rubric scoring, and task type routing.

### Changed

- Orchestrator synced with production: `ensure_agent_messages_table()`, `post_agent_message()`, `read_agent_messages()`, `mark_messages_read()`, `format_messages_for_prompt()`, `ensure_agent_actions_table()`, `classify_error()`, `log_agent_action()`, `bulk_log_agent_actions()`, `get_action_summary()`.
- `run_agent_streaming()` — Added `task_id`, `run_id`, `cycle_number` params. Added action logging with SHA256 input hashing.
- `run_dev_test_loop()` — Added inter-agent message injection at each cycle start. Developer reads unread messages. Tester posts test results (pass/fail/blocked) as structured messages.
- Updated agent prompts: `developer.md`, `tester.md`, `code-reviewer.md`, `frontend-designer.md`, `_common.md` synced with production.
- `dispatch_config.json` — Updated turn limits (tester: 75, code-reviewer: 75, security-reviewer: 50). Added provider and Ollama configuration fields.
- `forgesmith_config.json` — Updated to rubric v12. Added OPRO config block.
- `schema.sql` — Added `agent_messages` and `agent_actions` tables with indexes.
- README updated with Coordinator Mode and Local LLM sections.

### Sanitized

- Removed all personal synced storage paths from orchestrator
- `PROJECT_DIRS` defaults to empty dict (populated via config)
- `GITHUB_OWNER` defaults to empty string
- `THEFORGE_DB` defaults to relative `Path("theforge.db")`
- All hardcoded `/data/` paths replaced with config-based or relative paths

## [2.1.0] - 2026-02-27

### Added

- **GEPA (Generalized Efficient Prompt Adaptation)** — DSPy-based automatic prompt evolution with A/B testing and automatic rollback. Evolves role prompts by reflecting on failure traces. Safety-capped at 20% change per cycle with protected sections. (`forgesmith_gepa.py`)
- **SIMBA (Systematic Identification of Mistakes and Behavioral Adjustments)** — Targeted rule generation from failure patterns. Contrasts successful vs failed episodes using Claude to generate specific improvement rules. Rules are effectiveness-scored and auto-pruned. (`forgesmith_simba.py`)
- **Context engineering** — Token-budget-aware prompt assembly in the orchestrator. Includes relevance-scored episode injection, lesson deduplication (60% overlap threshold), and priority-based trimming to keep prompts under 10K tokens.
- **Rubric evolution** — Rubric weights auto-adjust based on correlation with task success. Max ±10% weight change per criterion per cycle.
- **Effectiveness scoring** — All ForgeSmith changes (turn limits, prompt patches, SIMBA rules) are scored before/after for measurable impact. Changes below the rollback threshold (-0.3) are automatically reverted.
- **GEPA A/B testing** — Evolved prompts are tested in 50/50 split against baselines. Underperformers rolled back after 10+ tasks.
- **Episode Q-value updates (MemRL)** — Q-values updated after task completion: +0.1 on success, -0.05 on failure.
- **Comprehensive test suite** for `forgesmith_simba.py` (39 tests)

### Changed

- Updated README.md with full ForgeSmith prompt optimization documentation
- Updated User Guide with SIMBA, GEPA, context engineering, and rubric sections
- Updated architecture diagram to show ForgeSmith pipeline (SIMBA + GEPA + DSPy)
- ForgeSmith pipeline order expanded: COLLECT → ANALYZE → LESSONS → SIMBA → RUBRICS → APPLY → GEPA → LOG
- Database schema expanded to 28 tables (added ForgeSmith tables: lessons_learned, agent_episodes, forgesmith_runs, forgesmith_changes, rubric_scores, rubric_evolution_history)

### Configuration

New keys in `forgesmith_config.json`:
- `rubric_definitions` — Per-role scoring criteria and weights
- `rubric_evolution` — Weight evolution settings (max_weight_change_pct, min_sample_size, evolution_lookback_days)
- `suppression_cooldown_days` — Days before retrying suppressed changes
- `thresholds.max_turns_hit_rate` — Rate above which turn limits are increased
- `thresholds.turn_underuse_rate` — Rate below which turn limits are decreased

New keys in `dispatch_config.json`:
- `task_type_prompts` — Per-task-type prompt guidance (bug_fix, feature, refactor, test)

## [1.0.0] - 2026-02-07

### Added

- Initial release of Itzamna — portable installer for ForgeTeam
- Interactive setup wizard (`itzamna_setup.py`)
- Database schema (19 tables, 5 views)
- Agent prompt files for all roles
- Configuration file generation
- Claude Code MCP integration
- Documentation (Quick Start, User Guide, Custom Agents, Concurrency)
