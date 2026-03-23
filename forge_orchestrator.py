"""
EQUIPA Phase 5: Multi-Project Orchestration with Resource Allocation

Picks a task from TheForge, spawns Developer and Tester agents via claude -p,
gives them MCP access to TheForge, and iterates until tests pass or max cycles hit.

Manager mode: Provide a natural-language goal and the system plans tasks,
executes them via Dev+Tester loops, evaluates results, and iterates.

Parallel goals mode: Run multiple Manager loops across different projects
concurrently from a goals JSON file.

Auto-run mode: Automatically scan all projects for pending work, prioritize
them by task priority weights, and dispatch Dev+Test loops concurrently.

Setup repos mode: Initialize git and create GitHub private repos for projects.

Usage:
    python forge_orchestrator.py --task 63
    python forge_orchestrator.py --task 63 --dev-test
    python forge_orchestrator.py --project 21 --dev-test
    python forge_orchestrator.py --goal "Add a --version flag" --goal-project 21
    python forge_orchestrator.py --goal "Add dark mode" --goal-project 4 --max-rounds 2
    python forge_orchestrator.py --parallel-goals goals.json
    python forge_orchestrator.py --parallel-goals goals.json --max-concurrent 2 --dry-run
    python forge_orchestrator.py --auto-run --dry-run
    python forge_orchestrator.py --auto-run --only-project 21 --dry-run
    python forge_orchestrator.py --auto-run --max-tasks-per-project 1 --yes
    python forge_orchestrator.py --auto-run --dispatch-config custom.json --yes
    python forge_orchestrator.py --setup-repos --dry-run
    python forge_orchestrator.py --setup-repos-project 21
    python forge_orchestrator.py --task 63 --dry-run
    python forge_orchestrator.py --task 63 --model opus --max-turns 50

Copyright 2026 Forgeborn
"""

import argparse
import asyncio
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time
import uuid
from pathlib import Path

# Force unbuffered output so logs are visible in real-time via nohup/SSH
os.environ["PYTHONUNBUFFERED"] = "1"

# Phase 2 modular imports — output, messages, parsing, monitoring
from equipa.output import (  # noqa: E402
    _print_batch_summary,
    _print_task_summary,
    log,
    print_dev_test_summary,
    print_dispatch_plan,
    print_dispatch_summary,
    print_manager_summary,
    print_parallel_summary,
    print_summary,
)
from equipa.messages import (  # noqa: E402
    format_messages_for_prompt,
    mark_messages_read,
    post_agent_message,
    read_agent_messages,
)
from equipa.parsing import (  # noqa: E402
    CHARS_PER_TOKEN,
    EPISODE_REDUCTION_THRESHOLD,
    SYSTEM_PROMPT_TOKEN_HARD_LIMIT,
    SYSTEM_PROMPT_TOKEN_TARGET,
    _DEVELOPER_FILES_SCHEMA,
    _FAILURE_KEYWORD_PATTERNS,
    _FAILURE_PRIORITY,
    _TESTER_SCHEMA,
    _extract_marker_value,
    _extract_section,
    _parse_structured_output,
    _trim_prompt_section,
    build_compaction_summary,
    build_test_failure_context,
    classify_agent_failure,
    compact_agent_output,
    compute_initial_q_value,
    compute_keyword_overlap,
    deduplicate_lessons,
    estimate_tokens,
    parse_approach_summary,
    parse_developer_output,
    parse_error_patterns,
    parse_reflection,
    parse_tester_output,
    validate_output,
)
from equipa.monitoring import (  # noqa: E402
    LOOP_TERMINATE_THRESHOLD,
    LOOP_WARNING_THRESHOLD,
    LoopDetector,
    _build_streaming_result,
    _build_tool_signature,
    _check_cost_limit,
    _check_git_changes,
    _check_monologue,
    _check_stuck_phrases,
    _compute_output_hash,
    _detect_tool_loop,
    _get_budget_message,
    _parse_early_complete,
    _TOOL_SIG_KEY,
    adjust_dynamic_budget,
    calculate_dynamic_budget,
)

# Phase 3 modular imports — db, tasks, lessons, roles
from equipa.db import (  # noqa: E402
    _get_latest_agent_run_id,
    bulk_log_agent_actions,
    classify_error,
    ensure_schema,
    get_db_connection,
    log_agent_action,
    record_agent_run,
    update_task_status,
)
from equipa.tasks import (  # noqa: E402
    _get_task_status,
    fetch_next_todo,
    fetch_project_context,
    fetch_project_info,
    fetch_task,
    fetch_tasks_by_ids,
    get_task_complexity,
    resolve_project_dir,
    verify_task_updated,
)
from equipa.lessons import (  # noqa: E402
    _injected_episodes_by_task,
    format_episodes_for_injection,
    format_lessons_for_injection,
    get_relevant_episodes,
    record_agent_episode,
    update_episode_injection_count,
    update_episode_q_values,
    update_injected_episode_q_values_for_task,
    update_lesson_injection_count,
)
from equipa.roles import (  # noqa: E402
    _accumulate_cost,
    _apply_cost_totals,
    _discover_roles,
    get_role_model,
    get_role_turns,
)

# Import ForgeSmith functions for lesson injection
try:
    from forgesmith import get_relevant_lessons
except ImportError:
    # Fallback if forgesmith is not available
    def get_relevant_lessons(role=None, error_type=None, limit=5):
        return []

# Import lesson sanitization (PM-24, PM-28, PM-33)
try:
    from lesson_sanitizer import (
        sanitize_lesson_content,
        sanitize_error_signature,
        validate_lesson_structure,
        wrap_lessons_in_task_input,
    )
except ImportError:
    # Fallback stubs — no sanitization if module unavailable
    import logging as _sanitizer_logging
    _sanitizer_logging.warning(
        "SECURITY: lesson_sanitizer import failed — prompt sanitization DISABLED. "
        "Lessons injected into agent prompts will NOT be sanitized against prompt injection."
    )
    del _sanitizer_logging
    def sanitize_lesson_content(text):
        return text or ""
    def sanitize_error_signature(sig):
        return sig or ""
    def validate_lesson_structure(text):
        return bool(text)
    def wrap_lessons_in_task_input(text):
        return text or ""

# Import post-task quality scorer
try:
    from rubric_quality_scorer import score_and_store as quality_score_and_store
except ImportError:
    def quality_score_and_store(result_text, files_changed, role, agent_run_id,
                                task_id, project_id, db_path=None):
        return None


# Phase 4 modular imports — security, prompts, reflexion, agent_runner, preflight, loops, manager
from equipa.security import (  # noqa: E402
    _make_untrusted_delimiter,
    generate_skill_manifest,
    verify_skill_integrity,
    wrap_untrusted,
    write_skill_manifest,
)
from equipa.prompts import (  # noqa: E402
    _last_prompt_version,
    build_checkpoint_context,
    build_evaluator_prompt,
    build_planner_prompt,
    build_system_prompt,
    build_task_prompt,
)
from equipa.reflexion import (  # noqa: E402
    INITIAL_Q_VALUE,
    REFLEXION_PROMPT,
    maybe_run_reflexion,
    run_reflexion_agent,
)
from equipa.agent_runner import (  # noqa: E402
    build_cli_command,
    dispatch_agent,
    run_agent,
    run_agent_streaming,
    run_agent_with_retries,
)
from equipa.preflight import (  # noqa: E402
    _dispatch_autofix_agent,
    _handle_preflight_failure,
    _resolve_build_command,
    _run_install_cmd,
    auto_install_dependencies,
    preflight_build_check,
)
from equipa.loops import (  # noqa: E402
    _create_security_lessons,
    _extract_security_findings,
    run_dev_test_loop,
    run_quality_scoring,
    run_security_review,
)
from equipa.manager import (  # noqa: E402
    parse_evaluator_output,
    parse_planner_output,
    run_evaluator_agent,
    run_manager_loop,
    run_planner_agent,
)


# --- Constants (extracted to equipa/constants.py) ---

from equipa.constants import (  # noqa: E402
    AUTOFIX_COST_LIMIT,
    AUTOFIX_DEBUGGER_BUDGET,
    AUTOFIX_MAX_DEBUGGER_CYCLES,
    AUTOFIX_PLANNER_BUDGET,
    BUDGET_CHECK_INTERVAL,
    BUDGET_CRITICAL_THRESHOLD,
    BUDGET_HALFWAY_THRESHOLD,
    CHECKPOINT_DIR,
    COMPLEXITY_MULTIPLIERS,
    COST_ESTIMATE_PER_TURN,
    COST_LIMITS,
    DEFAULT_MAX_RETRIES,
    DEFAULT_MAX_TURNS,
    DEFAULT_MODEL,
    DEFAULT_ROLE_MODELS,
    DEFAULT_ROLE_TURNS,
    DEV_COMPACTION_THRESHOLD,
    DYNAMIC_BUDGET_BLOCKED_RATIO,
    DYNAMIC_BUDGET_EXTEND_TURNS,
    DYNAMIC_BUDGET_MIN_TURNS,
    DYNAMIC_BUDGET_START_RATIO,
    EARLY_TERM_EXEMPT_ROLES,
    EARLY_TERM_FINAL_WARN_TURNS,
    EARLY_TERM_KILL_TURNS,
    EARLY_TERM_STUCK_PHRASES,
    EARLY_TERM_WARN_TURNS,
    GITHUB_OWNER,
    GITIGNORE_TEMPLATES,
    MAX_CONTINUATIONS,
    MAX_DEV_TEST_CYCLES,
    MAX_FOLLOWUP_TASKS,
    MAX_MANAGER_ROUNDS,
    MAX_TASKS_PER_PLAN,
    MCP_CONFIG,
    MONOLOGUE_EXEMPT_TURNS,
    MONOLOGUE_THRESHOLD,
    NO_PROGRESS_LIMIT,
    PREFLIGHT_SKIP_KEYWORDS,
    PREFLIGHT_TIMEOUT,
    PRIORITY_ORDER,
    PROCESS_TIMEOUT,
    PROJECT_DIRS,
    PROMPTS_DIR,
    ROLE_PROMPTS,
    ROLE_SKILLS,
    SKILL_MANIFEST_FILE,
    SKILLS_BASE_DIR,
    TESTER_COMPACTION_THRESHOLD,
    THEFORGE_DB,
)

# --- Checkpoints (extracted to equipa/checkpoints.py) ---

from equipa.checkpoints import (  # noqa: E402
    clear_checkpoints,
    load_checkpoint,
    save_checkpoint,
)

# --- Git Operations (extracted to equipa/git_ops.py) ---

from equipa.git_ops import (  # noqa: E402
    _get_repo_env,
    _git_run,
    _is_git_repo,
    check_gh_installed,
    detect_project_language,
    setup_all_repos,
    setup_single_repo,
)

import equipa.constants as _equipa_constants  # noqa: E402


# generate_skill_manifest, write_skill_manifest, verify_skill_integrity extracted to equipa/security.py


# _accumulate_cost extracted to equipa/roles.py

# --- Provider Abstraction (Claude / Ollama) ---

def get_provider(role, dispatch_config=None):
    """Determine which provider to use for a given role.

    Checks dispatch_config for role-specific overrides like
    'provider_planner': 'ollama', falling back to the global 'provider' key,
    then defaulting to 'claude'.
    """
    if dispatch_config is None:
        return "claude"
    # Check role-specific override first
    role_key = f"provider_{role.replace('-', '_')}"
    provider = dispatch_config.get(role_key)
    if provider:
        return provider
    # Fall back to global provider setting
    return dispatch_config.get("provider", "claude")


def get_ollama_model(role, dispatch_config=None):
    """Get the Ollama model name for a given role.

    Checks for role-specific model override like 'ollama_model_planner',
    then falls back to global 'ollama_model'.
    """
    if dispatch_config is None:
        return "qwen3.5:27b"
    role_key = f"ollama_model_{role.replace('-', '_')}"
    model = dispatch_config.get(role_key)
    if model:
        return model
    return dispatch_config.get("ollama_model", "qwen3.5:27b")


def get_ollama_base_url(dispatch_config=None):
    """Get the Ollama base URL from config or environment."""
    if dispatch_config and "ollama_base_url" in dispatch_config:
        return dispatch_config["ollama_base_url"]
    return os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")


# --- Portable Configuration ---

def load_config():
    """Load forge_config.json if present alongside this script.

    Overrides THEFORGE_DB, PROJECT_DIRS, GITHUB_OWNER, MCP_CONFIG, and
    PROMPTS_DIR with values from the config file.  Falls back silently to
    the hardcoded defaults above when no config file exists.
    """
    global THEFORGE_DB, PROJECT_DIRS, GITHUB_OWNER, MCP_CONFIG, PROMPTS_DIR

    config_path = Path(__file__).parent / "forge_config.json"
    if not config_path.exists():
        return  # backward compatible — use hardcoded values

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        print(f"WARNING: Failed to read {config_path}: {exc}")
        return

    if "theforge_db" in cfg:
        THEFORGE_DB = Path(cfg["theforge_db"])
        _equipa_constants.THEFORGE_DB = THEFORGE_DB
    if "project_dirs" in cfg:
        # Support PROJECT_BASE_DIR env var: if a project path starts with
        # $PROJECT_BASE_DIR/, resolve it against the env var value.
        base_dir = os.environ.get("PROJECT_BASE_DIR", "")
        raw_dirs = cfg["project_dirs"]
        resolved = {}
        for k, v in raw_dirs.items():
            if base_dir and v.startswith("$PROJECT_BASE_DIR/"):
                v = v.replace("$PROJECT_BASE_DIR", base_dir, 1)
            resolved[k.lower()] = v
        PROJECT_DIRS = resolved
        _equipa_constants.PROJECT_DIRS = PROJECT_DIRS
    if "github_owner" in cfg:
        GITHUB_OWNER = cfg["github_owner"]
        _equipa_constants.GITHUB_OWNER = GITHUB_OWNER
    if "mcp_config" in cfg:
        MCP_CONFIG = Path(cfg["mcp_config"])
        _equipa_constants.MCP_CONFIG = MCP_CONFIG
    if "prompts_dir" in cfg:
        PROMPTS_DIR = Path(cfg["prompts_dir"])
        _equipa_constants.PROMPTS_DIR = PROMPTS_DIR


# _discover_roles extracted to equipa/roles.py


def _handle_add_project(name, project_dir):
    """Register a new project in the EQUIPA DB and update forge_config.json."""
    project_dir = str(Path(project_dir).resolve())

    # Insert into DB
    if not THEFORGE_DB.exists():
        print(f"ERROR: Database not found at {THEFORGE_DB}")
        sys.exit(1)

    conn = sqlite3.connect(str(THEFORGE_DB))
    try:
        codename = name.lower().replace(" ", "")
        conn.execute(
            "INSERT INTO projects (name, codename, status) VALUES (?, ?, 'active')",
            (name, codename),
        )
        conn.commit()
        project_id = conn.execute(
            "SELECT id FROM projects WHERE codename = ?", (codename,)
        ).fetchone()[0]
        print(f"Created project '{name}' (codename: {codename}, id: {project_id})")
    except sqlite3.IntegrityError:
        print(f"ERROR: Project '{name}' already exists in TheForge")
        conn.close()
        sys.exit(1)
    finally:
        conn.close()

    # Update forge_config.json if it exists
    config_path = Path(__file__).parent / "forge_config.json"
    if config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            cfg.setdefault("project_dirs", {})[codename] = project_dir
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=4)
            print(f"Updated {config_path} with project directory: {project_dir}")
        except (json.JSONDecodeError, OSError) as exc:
            print(f"WARNING: Could not update config: {exc}")
    else:
        print(f"NOTE: No forge_config.json found. Add project dir to PROJECT_DIRS manually.")

    print(f"\nProject '{name}' registered successfully.")
    print(f"  ID: {project_id}")
    print(f"  Dir: {project_dir}")


# Apply config and discover roles at module load time
load_config()
_discover_roles()

# --- Output Helper ---

# log() extracted to equipa/output.py


# --- Database Functions ---
# get_db_connection, update_task_status extracted to equipa/db.py


# record_agent_run, _get_latest_agent_run_id extracted to equipa/db.py


# run_quality_scoring extracted to equipa/loops.py


# --- Reflexion (Post-task self-reflection for learning) ---

# REFLEXION_PROMPT, INITIAL_Q_VALUE extracted to equipa/reflexion.py


# _SCHEMA_ENSURED, ensure_schema extracted to equipa/db.py


# --- Inter-Agent Message Channel ---

# post_agent_message, read_agent_messages, mark_messages_read,
# format_messages_for_prompt extracted to equipa/messages.py


# --- Agent Action Logging ---




# classify_error, log_agent_action, bulk_log_agent_actions extracted to equipa/db.py


# _extract_marker_value, parse_reflection, parse_approach_summary,
# _FAILURE_KEYWORD_PATTERNS, _FAILURE_PRIORITY extracted to equipa/parsing.py


# classify_agent_failure extracted to equipa/parsing.py


# parse_error_patterns, compute_initial_q_value extracted to equipa/parsing.py


# record_agent_episode extracted to equipa/lessons.py


# run_reflexion_agent extracted to equipa/reflexion.py


# maybe_run_reflexion extracted to equipa/reflexion.py


# fetch_task, fetch_next_todo, fetch_project_context, _get_task_status,
# fetch_project_info, fetch_tasks_by_ids extracted to equipa/tasks.py


# --- Prompt Building ---

# build_task_prompt extracted to equipa/prompts.py


# --- Context Engineering Helpers ---
# CHARS_PER_TOKEN, SYSTEM_PROMPT_TOKEN_TARGET, SYSTEM_PROMPT_TOKEN_HARD_LIMIT,
# EPISODE_REDUCTION_THRESHOLD, estimate_tokens, compute_keyword_overlap,
# deduplicate_lessons, _extract_section, compact_agent_output,
# _trim_prompt_section extracted to equipa/parsing.py


# format_lessons_for_injection, update_lesson_injection_count extracted to equipa/lessons.py


# --- Episode Injection (MemRL pattern) ---
# _injected_episodes_by_task, get_relevant_episodes, format_episodes_for_injection,
# update_episode_injection_count, update_episode_q_values,
# update_injected_episode_q_values_for_task extracted to equipa/lessons.py

# _last_prompt_version extracted to equipa/prompts.py


# build_system_prompt extracted to equipa/prompts.py


# get_task_complexity extracted to equipa/tasks.py
# get_role_turns, get_role_model extracted to equipa/roles.py


# --- Checkpoint/Resume ---
# save_checkpoint, load_checkpoint, clear_checkpoints extracted to equipa/checkpoints.py


# build_checkpoint_context extracted to equipa/prompts.py


# --- CLI Command Building ---

# build_cli_command extracted to equipa/agent_runner.py


# --- Agent Execution ---


# run_agent extracted to equipa/agent_runner.py


# run_agent_streaming extracted to equipa/agent_runner.py

# run_agent_with_retries extracted to equipa/agent_runner.py

# _run_install_cmd extracted to equipa/preflight.py

# auto_install_dependencies extracted to equipa/preflight.py

# _resolve_build_command extracted to equipa/preflight.py

# preflight_build_check extracted to equipa/preflight.py


# _dispatch_autofix_agent extracted to equipa/preflight.py

# _handle_preflight_failure extracted to equipa/preflight.py


# dispatch_agent extracted to equipa/agent_runner.py


# run_dev_test_loop extracted to equipa/loops.py

# run_security_review extracted to equipa/loops.py

# _extract_security_findings extracted to equipa/loops.py

# _create_security_lessons extracted to equipa/loops.py


# build_planner_prompt extracted to equipa/manager.py

# build_evaluator_prompt extracted to equipa/manager.py

# parse_planner_output extracted to equipa/manager.py

# parse_evaluator_output extracted to equipa/manager.py

# run_planner_agent extracted to equipa/manager.py

# run_evaluator_agent extracted to equipa/manager.py

# run_manager_loop extracted to equipa/manager.py

def load_goals_file(filepath):
    """Parse and validate a goals JSON file.

    Returns (defaults_dict, goals_list) tuple.
    Exits with error on invalid input.
    """
    path = Path(filepath)
    if not path.exists():
        print(f"ERROR: Goals file not found: {filepath}")
        sys.exit(1)

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"ERROR: Invalid JSON in goals file: {e}")
        sys.exit(1)

    if "goals" not in data or not isinstance(data["goals"], list):
        print("ERROR: Goals file must contain a 'goals' array")
        sys.exit(1)

    if not data["goals"]:
        print("ERROR: Goals array is empty")
        sys.exit(1)

    # Extract defaults
    defaults = {
        "max_concurrent": data.get("max_concurrent", 4),
        "model": data.get("model", DEFAULT_MODEL),
        "max_turns": data.get("max_turns", DEFAULT_MAX_TURNS),
        "max_rounds": data.get("max_rounds", MAX_MANAGER_ROUNDS),
    }

    # Validate each goal
    for i, g in enumerate(data["goals"]):
        if "goal" not in g:
            print(f"ERROR: Goal #{i + 1} missing 'goal' field")
            sys.exit(1)
        if "project_id" not in g:
            print(f"ERROR: Goal #{i + 1} missing 'project_id' field")
            sys.exit(1)

    return defaults, data["goals"]


def validate_goals(goals):
    """Validate goals: check project_ids exist, dirs exist, no duplicates.

    Returns list of resolved goal dicts with project_dir and project_info added.
    Exits with error on validation failure.
    """
    # Check for duplicate project_ids
    project_ids = [g["project_id"] for g in goals]
    seen = set()
    for pid in project_ids:
        if pid in seen:
            print(f"ERROR: Duplicate project_id {pid} in goals file. "
                  f"Two goals cannot target the same project (they'd write to the same directory).")
            sys.exit(1)
        seen.add(pid)

    resolved = []
    for i, g in enumerate(goals):
        project_info = fetch_project_info(g["project_id"])
        if not project_info:
            print(f"ERROR: Goal #{i + 1}: Project {g['project_id']} not found in TheForge")
            sys.exit(1)

        codename = project_info.get("codename", "").lower().strip()
        pname = project_info.get("name", "").lower().strip()
        project_dir = PROJECT_DIRS.get(codename) or PROJECT_DIRS.get(pname)

        if not project_dir:
            print(f"ERROR: Goal #{i + 1}: No directory mapped for project "
                  f"'{project_info.get('name', 'Unknown')}'")
            sys.exit(1)

        if not Path(project_dir).exists():
            print(f"ERROR: Goal #{i + 1}: Directory does not exist: {project_dir}")
            sys.exit(1)

        resolved.append({
            **g,
            "project_dir": project_dir,
            "project_info": project_info,
        })

    return resolved


async def run_single_goal(goal_entry, semaphore, index, defaults, args):
    """Run a single Manager loop for one goal, respecting the semaphore.

    Returns a result dict with goal info and outcome.
    """
    goal_text = goal_entry["goal"]
    project_id = goal_entry["project_id"]
    project_dir = goal_entry["project_dir"]
    project_name = goal_entry["project_info"].get("name", "Unknown")

    # Per-goal overrides or defaults
    model = goal_entry.get("model", defaults["model"])
    max_turns = goal_entry.get("max_turns", defaults["max_turns"])
    max_rounds = goal_entry.get("max_rounds", defaults["max_rounds"])

    # Create a namespace that looks like args for the manager loop
    goal_args = argparse.Namespace(
        model=model,
        max_turns=max_turns,
        max_rounds=max_rounds,
    )

    output = []  # Buffer all output for this goal
    log(f"\n[Goal {index + 1}] {goal_text}", output)
    log(f"  Project: {project_name} (ID: {project_id})", output)
    log(f"  Directory: {project_dir}", output)
    log(f"  Model: {model}, Max turns: {max_turns}, Max rounds: {max_rounds}", output)

    async with semaphore:
        log(f"\n[Goal {index + 1}] Acquired slot, starting...", output)
        project_context = fetch_project_context(project_id)

        try:
            outcome, rounds, completed, blocked, cost, duration = await run_manager_loop(
                goal_text, project_id, project_dir, project_context,
                goal_args, output=output,
            )
        except Exception as e:
            log(f"\n[Goal {index + 1}] EXCEPTION: {e}", output)
            return {
                "index": index,
                "goal": goal_text,
                "project_name": project_name,
                "project_id": project_id,
                "outcome": "exception",
                "error": str(e),
                "rounds": 0,
                "completed": [],
                "blocked": [],
                "cost": 0.0,
                "duration": 0.0,
                "output": output,
            }

        print_manager_summary(
            goal_text, outcome, rounds, completed, blocked, cost, duration,
            output=output,
        )

    return {
        "index": index,
        "goal": goal_text,
        "project_name": project_name,
        "project_id": project_id,
        "outcome": outcome,
        "rounds": rounds,
        "completed": completed,
        "blocked": blocked,
        "cost": cost,
        "duration": duration,
        "output": output,
    }


async def run_parallel_goals(resolved_goals, defaults, args):
    """Run multiple Manager loops concurrently with a semaphore.

    Prints each goal's buffered output as it completes, then a combined summary.
    """
    max_concurrent = args.max_concurrent or defaults["max_concurrent"]
    semaphore = asyncio.Semaphore(max_concurrent)

    print(f"\nStarting {len(resolved_goals)} parallel goals "
          f"(max {max_concurrent} concurrent)...\n")

    # Launch all goals
    tasks = [
        run_single_goal(g, semaphore, i, defaults, args)
        for i, g in enumerate(resolved_goals)
    ]

    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Print each goal's buffered output
    for r in results:
        if isinstance(r, Exception):
            print(f"\n{'!' * 60}")
            print(f"  GOAL EXCEPTION: {r}")
            print(f"{'!' * 60}")
            continue

        print(f"\n{'=' * 60}")
        print(f"  OUTPUT: Goal {r['index'] + 1} — {r['project_name']}")
        print(f"{'=' * 60}")
        for line in r.get("output", []):
            print(line)

    # Print combined summary
    print_parallel_summary(results)


# _print_batch_summary, print_parallel_summary, print_dispatch_summary
# extracted to equipa/output.py


# --- GitHub Repo Setup (Phase 4B) ---
# check_gh_installed extracted to equipa/git_ops.py


# detect_project_language, _get_repo_env, _git_run, setup_single_repo,
# setup_all_repos extracted to equipa/git_ops.py


# --- Auto-Run: DB Scanning & Scoring (Phase 5) ---

def scan_pending_work():
    """Query DB for all projects with todo tasks, grouped by priority.

    Returns a list of dicts:
    [
        {
            "project_id": 21,
            "project_name": "EQUIPA",
            "codename": "equipa",
            "status": "active",
            "tasks": [<task dicts sorted by priority>],
            "counts": {"critical": 0, "high": 2, "medium": 1, "low": 0},
            "total_todo": 3,
        },
        ...
    ]
    """
    conn = get_db_connection()
    try:
        rows = conn.execute(
            """
            SELECT t.id, t.title, t.description, t.priority, t.project_id,
                   p.name as project_name,
                   COALESCE(p.codename, LOWER(REPLACE(p.name, ' ', ''))) as codename,
                   p.status as project_status
            FROM tasks t
            LEFT JOIN projects p ON t.project_id = p.id
            WHERE t.status = 'todo'
            ORDER BY t.project_id, t.created_at ASC
            """,
        ).fetchall()

        # Group by project
        projects = {}
        for row in rows:
            row = dict(row)
            pid = row["project_id"]
            if pid not in projects:
                projects[pid] = {
                    "project_id": pid,
                    "project_name": row["project_name"],
                    "codename": row["codename"],
                    "status": (row.get("project_status") or "unknown").lower(),
                    "tasks": [],
                    "counts": {"critical": 0, "high": 0, "medium": 0, "low": 0},
                    "total_todo": 0,
                }
            projects[pid]["tasks"].append(row)
            projects[pid]["total_todo"] += 1
            priority = str(row.get("priority", "low")).lower()
            if priority in projects[pid]["counts"]:
                projects[pid]["counts"][priority] += 1

        # Sort tasks within each project by priority descending
        for proj in projects.values():
            proj["tasks"].sort(
                key=lambda t: PRIORITY_ORDER.get(
                    str(t.get("priority", "low")).lower(), 0
                ),
                reverse=True,
            )

        return list(projects.values())
    finally:
        conn.close()


def score_project(summary, config):
    """Score a project for dispatch priority.

    score = (critical*10) + (high*5) + (medium*2) + (low*1)
           + 3 if project status is 'active'
           + priority_boost from config
    """
    counts = summary["counts"]
    score = (
        counts.get("critical", 0) * 10
        + counts.get("high", 0) * 5
        + counts.get("medium", 0) * 2
        + counts.get("low", 0) * 1
    )

    if summary.get("status") == "active":
        score += 3

    # Apply manual boost from config
    codename = summary.get("codename", "").lower()
    boost = config.get("priority_boost", {})
    if codename in boost:
        score += boost[codename]
    # Also check by project_id string
    pid_str = str(summary.get("project_id", ""))
    if pid_str in boost:
        score += boost[pid_str]

    summary["score"] = score
    return score


# --- Auto-Run: Config Loading & Filters (Phase 5) ---

DEFAULT_FEATURE_FLAGS = {
    "language_prompts": True,
    "hooks": False,
    "mcp_health": False,
    "forgesmith_lessons": True,
    "forgesmith_episodes": True,
    "gepa_ab_testing": False,
    "security_review": True,
    "quality_scoring": True,
    "anti_compaction_state": True,
}

DEFAULT_DISPATCH_CONFIG = {
    "max_concurrent": 8,
    "model": "sonnet",
    "max_turns": 25,
    "max_tasks_per_project": 3,
    "skip_projects": [],
    "priority_boost": {},
    "only_projects": [],
    "security_review": False,
    "features": dict(DEFAULT_FEATURE_FLAGS),
}


def is_feature_enabled(dispatch_config, feature_name):
    """Check if a feature flag is enabled.

    Reads from dispatch_config["features"][feature_name]. Falls back to
    DEFAULT_FEATURE_FLAGS if the feature is not in the config.

    Returns True/False. Unknown features default to False.
    """
    if dispatch_config is None:
        return DEFAULT_FEATURE_FLAGS.get(feature_name, False)
    features = dispatch_config.get("features", {})
    return features.get(feature_name, DEFAULT_FEATURE_FLAGS.get(feature_name, False))


def load_dispatch_config(filepath):
    """Load dispatch_config.json preferences.

    Returns a config dict with defaults for any missing keys.
    Falls back to defaults entirely if file not found.
    """
    config = dict(DEFAULT_DISPATCH_CONFIG)

    if filepath is None:
        # Try default location
        filepath = Path(__file__).parent / "dispatch_config.json"
    else:
        filepath = Path(filepath)

    if not filepath.exists():
        return config

    try:
        data = json.loads(filepath.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        print(f"WARNING: Could not load dispatch config '{filepath}': {e}")
        print("  Using defaults.")
        return config

    # Merge loaded values over defaults
    for key in DEFAULT_DISPATCH_CONFIG:
        if key in data:
            config[key] = data[key]

    # Deep-merge features: user's partial features dict is overlaid on defaults
    # so specifying e.g. {"features": {"hooks": true}} does not wipe other flags.
    if "features" in data and isinstance(data["features"], dict):
        merged_features = dict(DEFAULT_FEATURE_FLAGS)
        merged_features.update(data["features"])
        config["features"] = merged_features

    # Also merge any extra keys not in defaults (model_developer, model_epic, etc.)
    for key in data:
        if key not in config:
            config[key] = data[key]

    return config


def apply_dispatch_filters(work, config, args):
    """Apply skip_projects, only_projects, and --only-project filters.

    Returns filtered list of project summaries.
    """
    filtered = list(work)

    # --only-project CLI args take highest priority
    cli_only = getattr(args, "only_project", None) or []
    if cli_only:
        cli_only_set = set(cli_only)
        filtered = [p for p in filtered if p["project_id"] in cli_only_set]
        return filtered

    # Config-level only_projects (whitelist mode)
    config_only = config.get("only_projects", [])
    if config_only:
        only_set = set()
        for item in config_only:
            if isinstance(item, int):
                only_set.add(item)
            elif isinstance(item, str):
                # Match by codename
                for p in filtered:
                    if p.get("codename", "").lower() == item.lower():
                        only_set.add(p["project_id"])
        filtered = [p for p in filtered if p["project_id"] in only_set]
        return filtered

    # Config-level skip_projects
    skip_list = config.get("skip_projects", [])
    if skip_list:
        skip_set = set()
        for item in skip_list:
            if isinstance(item, int):
                skip_set.add(item)
            elif isinstance(item, str):
                for p in filtered:
                    if p.get("codename", "").lower() == item.lower():
                        skip_set.add(p["project_id"])
        filtered = [p for p in filtered if p["project_id"] not in skip_set]

    return filtered


# --- Auto-Run: Per-Project Task Runner (Phase 5) ---

async def run_project_tasks(project_summary, config, args, output=None):
    """Run Dev+Test loops on todo tasks for one project, in priority order.

    Returns a dict with results per task.
    """
    project_id = project_summary["project_id"]
    codename = project_summary.get("codename", "unknown")
    tasks = project_summary["tasks"]

    # Apply max_tasks_per_project cap
    max_tasks = getattr(args, "max_tasks_per_project", None)
    if max_tasks is None:
        max_tasks = config.get("max_tasks_per_project", 5)
    if len(tasks) > max_tasks:
        log(f"  [{codename}] Capping to {max_tasks} tasks (of {len(tasks)} todo)", output)
        tasks = tasks[:max_tasks]

    # Resolve project directory
    codename_lower = codename.lower().strip()
    project_dir = PROJECT_DIRS.get(codename_lower)
    if not project_dir:
        log(f"  [{codename}] ERROR: No directory mapped. Skipping.", output)
        return {
            "project_id": project_id,
            "codename": codename,
            "tasks_attempted": 0,
            "tasks_completed": [],
            "tasks_blocked": [],
            "tasks_skipped": len(tasks),
            "error": "No directory mapped",
            "total_cost": 0.0,
            "total_duration": 0.0,
        }

    if not Path(project_dir).exists():
        log(f"  [{codename}] ERROR: Directory does not exist: {project_dir}. Skipping.", output)
        return {
            "project_id": project_id,
            "codename": codename,
            "tasks_attempted": 0,
            "tasks_completed": [],
            "tasks_blocked": [],
            "tasks_skipped": len(tasks),
            "error": "Directory does not exist",
            "total_cost": 0.0,
            "total_duration": 0.0,
        }

    project_context = fetch_project_context(project_id)

    completed = []
    blocked = []
    total_cost = 0.0
    total_duration = 0.0

    # Build args namespace for dev-test loop
    task_args = argparse.Namespace(
        model=config.get("model", args.model),
        max_turns=config.get("max_turns", args.max_turns),
        dispatch_config=config,  # pass config so get_role_turns can read per-role limits
    )

    for i, task_row in enumerate(tasks, 1):
        task_id = task_row["id"]
        log(f"\n  [{codename}] Task {i}/{len(tasks)}: #{task_id} - {task_row['title']}", output)

        # Re-fetch task to get full data with project info
        task = fetch_task(task_id)
        if not task:
            log(f"  [{codename}] Task #{task_id} not found in DB. Skipping.", output)
            continue

        # Check if still todo
        if task.get("status") != "todo":
            log(f"  [{codename}] Task #{task_id} status is '{task.get('status')}'. Skipping.", output)
            continue

        result, cycles, outcome = await run_dev_test_loop(
            task, project_dir, project_context, task_args, output=output,
        )
        total_duration += result.get("duration", 0)
        if result.get("cost"):
            total_cost += result["cost"]

        # Orchestrator-side DB update (don't rely on agent)
        update_task_status(task_id, outcome, output=output)

        # ForgeSmith telemetry
        task_role = task.get("role") or "developer"
        record_agent_run(
            task, result, outcome, role=task_role,
            model=get_role_model(task_role, task_args, task=task),
            max_turns=get_role_turns(task_role, task_args, task=task),
            cycle_number=cycles, output=output,
        )

        # Post-task quality scoring (on success only)
        if outcome in ("tests_passed", "no_tests"):
            run_quality_scoring(task, result, outcome, role=task_role, output=output,
                                dispatch_config=config)

        # Reflexion: record episode and capture self-reflection
        await maybe_run_reflexion(task, result, outcome, role=task_role, output=output)

        # MemRL: update q_values of episodes that were injected into this task's prompt
        update_injected_episode_q_values_for_task(task_id, outcome, output=output)

        if outcome in ("tests_passed", "no_tests"):
            completed.append(task)
            log(f"  [{codename}] Task #{task_id}: COMPLETED ({outcome})", output)
        else:
            blocked.append(task)
            log(f"  [{codename}] Task #{task_id}: BLOCKED ({outcome})", output)

    return {
        "project_id": project_id,
        "codename": codename,
        "tasks_attempted": len(tasks),
        "tasks_completed": completed,
        "tasks_blocked": blocked,
        "tasks_skipped": 0,
        "error": None,
        "total_cost": total_cost,
        "total_duration": total_duration,
    }


async def run_project_dispatch(project_summary, semaphore, config, args):
    """Wrapper for concurrent execution of one project's tasks.

    Acquires semaphore slot, runs tasks, returns result with buffered output.
    """
    codename = project_summary.get("codename", "unknown")
    output = []

    log(f"\n[{codename}] Queued ({project_summary['total_todo']} todo tasks, "
        f"score: {project_summary.get('score', '?')})", output)

    async with semaphore:
        log(f"[{codename}] Acquired slot, starting...", output)

        try:
            result = await run_project_tasks(
                project_summary, config, args, output=output,
            )
        except Exception as e:
            log(f"[{codename}] EXCEPTION: {e}", output)
            result = {
                "project_id": project_summary["project_id"],
                "codename": codename,
                "tasks_attempted": 0,
                "tasks_completed": [],
                "tasks_blocked": [],
                "tasks_skipped": project_summary["total_todo"],
                "error": str(e),
                "total_cost": 0.0,
                "total_duration": 0.0,
            }

    result["output"] = output
    return result


async def run_auto_dispatch(scored, config, args):
    """Run all project dispatches concurrently with semaphore.

    Prints each project's buffered output as it completes, then summary.
    """
    max_concurrent = config.get("max_concurrent", 4)
    semaphore = asyncio.Semaphore(max_concurrent)

    print(f"\nDispatching {len(scored)} projects "
          f"(max {max_concurrent} concurrent)...\n")

    coros = [
        run_project_dispatch(proj, semaphore, config, args)
        for proj in scored
    ]

    results = await asyncio.gather(*coros, return_exceptions=True)

    # Print each project's buffered output
    for r in results:
        if isinstance(r, Exception):
            print(f"\n{'!' * 60}")
            print(f"  PROJECT EXCEPTION: {r}")
            print(f"{'!' * 60}")
            continue

        print(f"\n{'=' * 60}")
        print(f"  OUTPUT: {r.get('codename', '?')}")
        print(f"{'=' * 60}")
        for line in r.get("output", []):
            print(line)

    # Print combined summary
    print_dispatch_summary(results)


# print_dispatch_plan, print_dispatch_summary extracted to equipa/output.py


def parse_task_ids(task_str):
    """Parse comma-separated IDs or ranges into a list of ints.

    Examples: "109,110,111" -> [109, 110, 111]
              "109-114" -> [109, 110, 111, 112, 113, 114]
              "109,112-114" -> [109, 112, 113, 114]
    """
    ids = []
    for part in task_str.split(","):
        part = part.strip()
        if "-" in part:
            start, end = part.split("-", 1)
            ids.extend(range(int(start), int(end) + 1))
        else:
            ids.append(int(part))
    return ids


async def run_parallel_tasks(task_ids, args):
    """Run multiple tasks concurrently with dev-test loops.

    All tasks must belong to the same project (for safety).
    """
    # Fetch all tasks
    tasks = fetch_tasks_by_ids(task_ids)
    if not tasks:
        print("ERROR: No tasks found for given IDs.")
        return

    # Verify all tasks are from the same project
    project_ids = set(t.get("project_id") for t in tasks)
    if len(project_ids) > 1:
        print(f"ERROR: --tasks requires all tasks from the same project. "
              f"Found project IDs: {project_ids}")
        return

    project_id = tasks[0].get("project_id")
    project_dir = resolve_project_dir(tasks[0])
    if not project_dir:
        print(f"ERROR: Could not resolve project directory.")
        return
    if not Path(project_dir).exists():
        print(f"ERROR: Project directory does not exist: {project_dir}")
        return

    project_context = fetch_project_context(project_id)
    max_concurrent = getattr(args, "max_concurrent", None) or 4
    semaphore = asyncio.Semaphore(max_concurrent)

    print(f"\nParallel task execution: {len(tasks)} tasks, max {max_concurrent} concurrent")
    for t in tasks:
        print(f"  - #{t['id']}: {t['title']}")

    if not args.yes:
        response = input("\nProceed? (y/n): ").strip().lower()
        if response != "y":
            print("Aborted.")
            return

    # Create per-task git worktrees for filesystem isolation
    worktree_dirs = {}
    worktree_base = Path(project_dir) / ".forge-worktrees"
    use_worktrees = len(tasks) > 1 and _is_git_repo(project_dir)

    if use_worktrees:
        worktree_base.mkdir(exist_ok=True)
        for t in tasks:
            branch_name = f"forge-task-{t['id']}"
            wt_path = worktree_base / f"task-{t['id']}"
            try:
                # Clean up stale worktree if exists
                if wt_path.exists():
                    subprocess.run(["git", "worktree", "remove", "--force", str(wt_path)],
                                   cwd=project_dir, capture_output=True)
                # Create worktree from current HEAD
                subprocess.run(
                    ["git", "worktree", "add", "-b", branch_name, str(wt_path), "HEAD"],
                    cwd=project_dir, capture_output=True, check=True,
                )
                worktree_dirs[t["id"]] = str(wt_path)
                print(f"  [Isolation] Task #{t['id']} -> {wt_path.name}")
            except subprocess.CalledProcessError as e:
                # Fallback: if worktree creation fails, try without -b (branch may exist)
                try:
                    subprocess.run(["git", "branch", "-D", branch_name],
                                   cwd=project_dir, capture_output=True)
                    subprocess.run(
                        ["git", "worktree", "add", "-b", branch_name, str(wt_path), "HEAD"],
                        cwd=project_dir, capture_output=True, check=True,
                    )
                    worktree_dirs[t["id"]] = str(wt_path)
                    print(f"  [Isolation] Task #{t['id']} -> {wt_path.name} (retry)")
                except Exception:
                    print(f"  [Isolation] WARNING: Could not create worktree for task #{t['id']}, using shared dir")

    async def run_one_task(task):
        output = []
        # Use worktree if available, otherwise shared project_dir
        task_dir = worktree_dirs.get(task["id"], project_dir)
        async with semaphore:
            log(f"\n[Task #{task['id']}] Starting: {task['title']}", output)
            result, cycles, outcome = await run_dev_test_loop(
                task, task_dir, project_context, args, output=output,
            )
            update_task_status(task["id"], outcome, output=output)
            log(f"[Task #{task['id']}] Done: {outcome} ({cycles} cycles)", output)
            # Record telemetry (was missing from parallel path)
            task_role = task.get("role") or "developer"
            record_agent_run(
                task, result, outcome, role=task_role,
                model=get_role_model(task_role, args, task=task),
                max_turns=get_role_turns(task_role, args, task=task),
                cycle_number=cycles, output=output,
            )

            # Mark for post-gather sequential merge (avoid parallel merge conflicts)
            merge_ok = False
            needs_merge = task["id"] in worktree_dirs and outcome in ("tests_passed", "no_tests")

            return {
                "task": task,
                "result": result,
                "cycles": cycles,
                "outcome": outcome,
                "output": output,
                "merge_ok": merge_ok,
                "needs_merge": needs_merge if 'needs_merge' in dir() else False,
            }

    results = await asyncio.gather(
        *[run_one_task(t) for t in tasks],
        return_exceptions=True,
    )

    # Print results
    print(f"\n{'#' * 60}")
    print("PARALLEL TASKS SUMMARY")
    print(f"{'#' * 60}")

    completed = []
    blocked = []
    total_cost = 0.0
    total_duration = 0.0

    for r in results:
        if isinstance(r, Exception):
            print(f"\n  EXCEPTION: {r}")
            continue

        task = r["task"]
        outcome = r["outcome"]
        result = r["result"]

        # Print buffered output
        for line in r.get("output", []):
            print(line)

        cost = result.get("cost", 0) or 0
        duration = result.get("duration", 0)
        total_cost += cost
        total_duration += duration

        if outcome in ("tests_passed", "no_tests"):
            completed.append(task)
            print(f"\n  #{task['id']}: COMPLETED ({outcome}, {r['cycles']} cycles, {duration:.0f}s)")
        else:
            blocked.append(task)
            print(f"\n  #{task['id']}: BLOCKED ({outcome}, {r['cycles']} cycles, {duration:.0f}s)")

    print(f"\nTotal: {len(completed)} completed, {len(blocked)} blocked")
    print(f"Duration: {total_duration:.0f}s total")
    if total_cost > 0:
        print(f"Cost: ${total_cost:.4f}")
    print(f"{'#' * 60}")

    # Sequential merge — merge task branches one at a time to avoid conflicts
    if use_worktrees:
        merged_tasks_seq = set()
        merge_candidates = []
        for r in results:
            if isinstance(r, Exception):
                continue
            if r.get("needs_merge", False) or (r["task"]["id"] in worktree_dirs and r["outcome"] in ("tests_passed", "no_tests")):
                merge_candidates.append(r)

        for r in merge_candidates:
            task_id = r["task"]["id"]
            branch_name = f"forge-task-{task_id}"
            try:
                # Stash any uncommitted changes first
                subprocess.run(["git", "stash"], cwd=project_dir, capture_output=True)
                merge_result = subprocess.run(
                    ["git", "merge", "--no-edit", branch_name],
                    cwd=project_dir, capture_output=True, text=True,
                )
                if merge_result.returncode == 0:
                    print(f"  [Isolation] Merged task #{task_id} into main")
                    r["merge_ok"] = True
                    merged_tasks_seq.add(task_id)
                else:
                    # Try rebase-then-merge for conflicts
                    subprocess.run(["git", "merge", "--abort"],
                                   cwd=project_dir, capture_output=True)
                    # Attempt rebase
                    rebase_result = subprocess.run(
                        ["git", "rebase", "HEAD", branch_name],
                        cwd=project_dir, capture_output=True, text=True,
                    )
                    if rebase_result.returncode == 0:
                        # Try merge again after rebase
                        merge2 = subprocess.run(
                            ["git", "merge", "--no-edit", branch_name],
                            cwd=project_dir, capture_output=True, text=True,
                        )
                        if merge2.returncode == 0:
                            print(f"  [Isolation] Merged task #{task_id} (after rebase)")
                            r["merge_ok"] = True
                            merged_tasks_seq.add(task_id)
                        else:
                            subprocess.run(["git", "merge", "--abort"],
                                           cwd=project_dir, capture_output=True)
                            print(f"  [Isolation] Merge FAILED for task #{task_id} (conflict after rebase)")
                            print(f"  [Isolation] Branch '{branch_name}' PRESERVED")
                    else:
                        subprocess.run(["git", "rebase", "--abort"],
                                       cwd=project_dir, capture_output=True)
                        print(f"  [Isolation] Merge FAILED for task #{task_id}: {merge_result.stderr[:200]}")
                        print(f"  [Isolation] Branch '{branch_name}' PRESERVED")
                # Pop stash if anything was stashed
                subprocess.run(["git", "stash", "pop"], cwd=project_dir,
                               capture_output=True, text=True)
            except Exception as e:
                print(f"  [Isolation] Merge error for task #{task_id}: {e}")

    # Clean up worktrees — only delete branches that were successfully merged
    if use_worktrees:
        # Collect merge status from results
        merged_tasks = set()
        for r in results:
            if isinstance(r, Exception):
                continue
            if r.get("merge_ok"):
                merged_tasks.add(r["task"]["id"])

        for task_id, wt_path in worktree_dirs.items():
            try:
                branch_name = f"forge-task-{task_id}"
                # Clean up ephemeral agent state file before removing worktree
                state_file = Path(wt_path) / ".forge-state.json"
                if state_file.exists():
                    state_file.unlink()
                # Always remove the worktree directory (it's a working copy)
                subprocess.run(["git", "worktree", "remove", "--force", wt_path],
                               cwd=project_dir, capture_output=True)
                if task_id in (merged_tasks_seq if use_worktrees else set()):
                    # Branch was merged — safe to delete
                    subprocess.run(["git", "branch", "-D", branch_name],
                                   cwd=project_dir, capture_output=True)
                else:
                    # Branch was NOT merged — PRESERVE it so work isn't lost
                    print(f"  [Isolation] Keeping branch '{branch_name}' (unmerged work)")
            except Exception:
                pass
        # Clean up worktree base dir if empty
        try:
            worktree_base.rmdir()
        except OSError:
            pass


# --- Main ---


async def _post_task_telemetry(task, result, outcome, role, model, max_turns,
                               cycle_number=None, output=None, dispatch_config=None):
    """Run all post-task telemetry: DB update, recording, scoring, reflexion, MemRL."""
    update_task_status(task["id"], outcome, output=output)
    record_agent_run(task, result, outcome, role=role, model=model,
                     max_turns=max_turns, cycle_number=cycle_number)
    if outcome in ("tests_passed", "no_tests"):
        run_quality_scoring(task, result, outcome, role=role, output=output,
                            dispatch_config=dispatch_config)
    await maybe_run_reflexion(task, result, outcome, role=role, output=output)
    update_injected_episode_q_values_for_task(task["id"], outcome, output=output)

async def async_main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="EQUIPA: Run AI agents on TheForge tasks"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--task", type=int, help="Task ID to work on")
    group.add_argument("--tasks", type=str, metavar="IDS",
                        help="Comma-separated task IDs or range (e.g. 109,110,111 or 109-114) for parallel execution")
    group.add_argument("--project", type=int, help="Project ID (auto-pick next todo task)")
    group.add_argument("--goal", type=str, help="High-level goal for Manager mode")
    group.add_argument("--parallel-goals", type=str, metavar="FILE",
                        help="Path to goals JSON file for parallel execution")
    group.add_argument("--setup-repos", action="store_true",
                        help="Init git + GitHub private repo for ALL projects")
    group.add_argument("--setup-repos-project", type=int, metavar="ID",
                        help="Init git + GitHub private repo for a single project")
    group.add_argument("--auto-run", action="store_true",
                        help="Auto-scan projects and dispatch work by priority")
    group.add_argument("--add-project", type=str, metavar="NAME",
                        help="Register a new project in EQUIPA DB and config")
    group.add_argument("--regenerate-manifest", action="store_true",
                        help="Regenerate skill_manifest.json with SHA-256 hashes of all prompt/skill files")

    parser.add_argument("--project-dir", type=str, metavar="PATH",
                        help="Project directory (used with --add-project)")
    parser.add_argument("--goal-project", type=int, help="Project ID (required with --goal)")
    parser.add_argument("--dispatch-config", type=str, metavar="FILE", default=None,
                        help="Path to dispatch config JSON (default: dispatch_config.json)")
    parser.add_argument("--max-tasks-per-project", type=int, default=None, metavar="N",
                        help="Cap tasks attempted per project per run")
    parser.add_argument("--only-project", type=int, action="append", default=None,
                        metavar="ID", help="Only run this project (repeatable)")
    parser.add_argument("--max-rounds", type=int, default=MAX_MANAGER_ROUNDS,
                        help=f"Max manager rounds (default: {MAX_MANAGER_ROUNDS})")
    parser.add_argument("--max-concurrent", type=int, default=None,
                        help="Override max concurrent goals (default: from goals file or 4)")
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"Model to use (default: {DEFAULT_MODEL})")
    parser.add_argument("--max-turns", type=int, default=DEFAULT_MAX_TURNS, help=f"Max agent turns (default: {DEFAULT_MAX_TURNS})")
    # Dynamically discover available roles from prompts directory
    _available_roles = sorted([
        f.stem for f in (Path(__file__).parent / "prompts").glob("*.md")
        if not f.name.startswith("_")
    ]) if (Path(__file__).parent / "prompts").exists() else ["developer", "tester", "security-reviewer"]
    parser.add_argument("--role", default="developer", choices=_available_roles,
                        help=f"Agent role (available: {', '.join(_available_roles)}) (default: developer)")
    parser.add_argument("--retries", type=int, default=DEFAULT_MAX_RETRIES, help=f"Max retry attempts (default: {DEFAULT_MAX_RETRIES})")
    parser.add_argument("--dev-test", action="store_true", help="Enable Dev+Tester iteration loop mode")
    parser.add_argument("--security-review", action="store_true", default=None,
                        help="Run security review after dev-test passes (default: from dispatch config)")
    parser.add_argument("--provider", choices=["claude", "ollama"], default=None,
                        help="Force provider for all agents (default: from dispatch config)")
    parser.add_argument("--dry-run", action="store_true", help="Print command without executing")
    parser.add_argument("--yes", "-y", action="store_true", help="Skip confirmation prompt")

    args = parser.parse_args()

    # Auto-detect non-TTY (nohup, SSH pipe, etc.) and default to --yes
    if not args.yes and not sys.stdin.isatty():
        args.yes = True
        print("Non-interactive mode detected (stdin is not a TTY). Auto-enabling --yes.")

    # Validate --goal requires --goal-project
    if args.goal and not args.goal_project:
        parser.error("--goal requires --goal-project <project_id>")

    # Warn if --dev-test combined with --role
    if args.dev_test and args.role != "developer":
        print(f"WARNING: --dev-test mode ignores --role ('{args.role}'). "
              f"Loop uses Developer + Tester automatically.")

    # Load dispatch config globally so model tiering and adaptive turns work in all modes
    args.dispatch_config = load_dispatch_config(args.dispatch_config)

    # --- Regenerate skill manifest mode ---
    if args.regenerate_manifest:
        write_skill_manifest()
        return

    # --- Add project mode ---
    if args.add_project:
        if not args.project_dir:
            parser.error("--add-project requires --project-dir <path>")
        _handle_add_project(args.add_project, args.project_dir)
        return

    # --- Setup repos mode (Phase 4B) ---
    if args.setup_repos or args.setup_repos_project:
        setup_all_repos(args)
        return

    # --- Auto-run mode (Phase 5) ---
    if args.auto_run:
        dispatch_config = args.dispatch_config

        # CLI overrides
        if args.max_concurrent is not None:
            dispatch_config["max_concurrent"] = args.max_concurrent
        if args.max_tasks_per_project is not None:
            dispatch_config["max_tasks_per_project"] = args.max_tasks_per_project

        # Scan DB for pending work
        print("Scanning TheForge for pending work...")
        work = scan_pending_work()
        if not work:
            print("No projects with todo tasks found.")
            return

        # Apply filters
        work = apply_dispatch_filters(work, dispatch_config, args)
        if not work:
            print("No projects match filters (check --only-project, skip_projects, only_projects).")
            return

        # Score and sort
        for proj in work:
            score_project(proj, dispatch_config)
        work.sort(key=lambda p: p.get("score", 0), reverse=True)

        # Dry run: show plan and exit
        if args.dry_run:
            print(f"\n--- DRY RUN (Auto-Run) ---")
            print_dispatch_plan(work, dispatch_config)
            print(f"\n--- END DRY RUN ---")
            return

        # Show plan and confirm
        print_dispatch_plan(work, dispatch_config)

        if not args.yes:
            response = input("\nProceed with dispatch? (y/n): ").strip().lower()
            if response != "y":
                print("Aborted.")
                return

        # Dispatch
        await run_auto_dispatch(work, dispatch_config, args)
        return

    # --- Parallel goals mode (Phase 4A) ---
    if args.parallel_goals:
        defaults, goals = load_goals_file(args.parallel_goals)
        resolved_goals = validate_goals(goals)

        # Apply per-goal defaults from file, allow CLI overrides
        if args.max_concurrent is not None:
            defaults["max_concurrent"] = args.max_concurrent

        if args.dry_run:
            print(f"\n--- DRY RUN (Parallel Goals) ---")
            print(f"Goals file: {args.parallel_goals}")
            print(f"Goals: {len(resolved_goals)}")
            print(f"Max concurrent: {defaults['max_concurrent']}")
            print(f"Default model: {defaults['model']}")
            print(f"Default max turns: {defaults['max_turns']}")
            print(f"Default max rounds: {defaults['max_rounds']}")
            print()
            for i, g in enumerate(resolved_goals):
                model = g.get("model", defaults["model"])
                print(f"  [{i + 1}] Project: {g['project_info']['name']} (ID: {g['project_id']})")
                print(f"      Goal: {g['goal'][:80]}")
                print(f"      Dir: {g['project_dir']}")
                print(f"      Model: {model}")
                planner_prompt = build_planner_prompt(
                    g["goal"], g["project_id"], g["project_dir"],
                    fetch_project_context(g["project_id"]),
                )
                print(f"      Planner prompt: {len(planner_prompt)} chars")
                print()
            print(f"--- END DRY RUN ---")
            return

        # Confirm
        if not args.yes:
            print(f"\nAbout to run {len(resolved_goals)} goals "
                  f"(max {defaults['max_concurrent']} concurrent).")
            for i, g in enumerate(resolved_goals):
                print(f"  [{i + 1}] {g['project_info']['name']}: {g['goal'][:60]}")
            response = input("\nProceed? (y/n): ").strip().lower()
            if response != "y":
                print("Aborted.")
                return

        await run_parallel_goals(resolved_goals, defaults, args)
        return

    # --- Manager mode (Phase 3) ---
    if args.goal:
        project_info = fetch_project_info(args.goal_project)
        if not project_info:
            print(f"ERROR: Project {args.goal_project} not found in TheForge")
            sys.exit(1)

        # Resolve project directory from project info
        codename = project_info.get("codename", "").lower().strip()
        project_name = project_info.get("name", "").lower().strip()
        project_dir = PROJECT_DIRS.get(codename) or PROJECT_DIRS.get(project_name)

        if not project_dir:
            print(f"ERROR: Could not find project directory for '{project_info.get('name', 'Unknown')}'")
            print("Known projects:", ", ".join(sorted(PROJECT_DIRS.keys())))
            sys.exit(1)

        if not Path(project_dir).exists():
            print(f"ERROR: Project directory does not exist: {project_dir}")
            sys.exit(1)

        project_context = fetch_project_context(args.goal_project)

        # Show goal info
        print(f"\nGoal: {args.goal}")
        print(f"Project: {project_info.get('name', 'Unknown')} (ID: {args.goal_project})")
        print(f"Directory: {project_dir}")
        print(f"Model: {args.model}")
        print(f"Max turns/agent: {args.max_turns}")
        print(f"Max rounds: {args.max_rounds}")

        if args.dry_run:
            # Show what the planner prompt would look like
            planner_prompt = build_planner_prompt(
                args.goal, args.goal_project, project_dir, project_context,
            )
            print(f"\n--- DRY RUN (Manager Mode) ---")
            print(f"Planner prompt: {len(planner_prompt)} chars")
            print(f"\nManager loop would run up to {args.max_rounds} rounds.")
            print(f"Each round: Planner -> Dev+Test loop per task -> Evaluator")
            print(f"\n--- END DRY RUN ---")
            return

        # Confirm before running
        if not args.yes:
            response = input("\nProceed? (y/n): ").strip().lower()
            if response != "y":
                print("Aborted.")
                return

        # Run the manager loop
        print(f"\nStarting Manager mode (max {args.max_rounds} rounds)...")
        outcome, rounds, completed, blocked, cost, duration = await run_manager_loop(
            args.goal, args.goal_project, project_dir, project_context, args,
        )

        # Print manager summary
        print_manager_summary(args.goal, outcome, rounds, completed, blocked, cost, duration)
        return

    # --- Parallel tasks mode ---
    if args.tasks:
        task_ids = parse_task_ids(args.tasks)
        if not task_ids:
            print("ERROR: Could not parse task IDs from --tasks argument.")
            sys.exit(1)

        if args.dry_run:
            tasks = fetch_tasks_by_ids(task_ids)
            print(f"\n--- DRY RUN (Parallel Tasks) ---")
            print(f"Tasks: {len(tasks)}")
            for t in tasks:
                print(f"  - #{t['id']}: {t['title']} ({t.get('project_name', '?')})")
            print(f"\n--- END DRY RUN ---")
            return

        await run_parallel_tasks(task_ids, args)
        return

    # --- Task/Project mode (Phase 1 & 2) ---

    # --- Fetch task ---
    if args.task:
        task = fetch_task(args.task)
        if not task:
            print(f"ERROR: Task {args.task} not found in TheForge")
            sys.exit(1)
    else:
        task = fetch_next_todo(args.project)
        if not task:
            print(f"No todo tasks found for project {args.project}")
            sys.exit(0)

    # Resolve project directory
    project_dir = resolve_project_dir(task)
    if not project_dir:
        print(f"ERROR: Could not find project directory for '{task.get('project_name', 'Unknown')}'")
        print("Known projects:", ", ".join(sorted(PROJECT_DIRS.keys())))
        sys.exit(1)

    # Verify project directory exists
    if not Path(project_dir).exists():
        print(f"ERROR: Project directory does not exist: {project_dir}")
        sys.exit(1)

    # Fetch project context
    project_context = fetch_project_context(task.get("project_id", 0))

    # Show task info
    complexity = get_task_complexity(task)
    mode_label = "Dev+Test loop" if args.dev_test else f"{args.role} (single agent)"
    print(f"\nTask #{task['id']}: {task['title']}")
    print(f"Project: {task.get('project_name', 'Unknown')}")
    print(f"Priority: {task.get('priority', 'medium')}")
    print(f"Complexity: {complexity}")
    print(f"Mode: {mode_label}")
    print(f"Directory: {project_dir}")

    if args.dev_test:
        # Use task-specified role if available, otherwise default to developer
        task_role = getattr(task, 'role', None) or (task.get('role') if isinstance(task, dict) else None) or "developer"
        dev_model = get_role_model(task_role, args, task=task)
        dev_turns = get_role_turns("developer", args, task=task)
        tester_model = get_role_model("tester", args, task=task)
        tester_turns = get_role_turns("tester", args, task=task)
        dev_budget, _ = calculate_dynamic_budget(dev_turns)
        tester_budget, _ = calculate_dynamic_budget(tester_turns)
        print(f"Developer: model={dev_model}, budget={dev_budget}/{dev_turns} (dynamic)")
        print(f"Tester: model={tester_model}, budget={tester_budget}/{tester_turns} (dynamic)")
        print(f"Max cycles: {MAX_DEV_TEST_CYCLES}")
        print(f"Compaction: Always (context engineering — never pass raw output between cycles)")
        # Check for checkpoint
        cp_text, cp_attempt = load_checkpoint(task['id'], role="developer")
        if cp_text:
            print(f"Checkpoint: Found from attempt #{cp_attempt} ({len(cp_text)} chars) — will auto-resume")
    else:
        role_model = get_role_model(args.role, args, task=task)
        role_turns = get_role_turns(args.role, args, task=task)
        role_budget, _ = calculate_dynamic_budget(role_turns)
        print(f"Model: {role_model}")
        print(f"Budget: {role_budget}/{role_turns} turns (dynamic)")
        print(f"Max retries: {args.retries}")

    if args.dry_run:
        # Build a sample prompt to show size
        system_prompt = build_system_prompt(task, project_context, project_dir, role="developer",
                                                  dispatch_config=getattr(args, "dispatch_config", None))
        dry_model = get_role_model("developer", args, task=task)
        dry_turns = get_role_turns("developer", args, task=task)
        cmd = build_cli_command(system_prompt, project_dir, dry_turns, dry_model, role="developer")

        print(f"\n--- DRY RUN ---")
        print(f"System prompt: {len(system_prompt)} chars, ~{estimate_tokens(system_prompt)} tokens")
        print(f"Command ({len(cmd)} args):")
        for i, part in enumerate(cmd):
            if i > 0 and cmd[i - 1] == "--append-system-prompt":
                print(f"  [system prompt: {len(part)} chars]")
            elif len(part) > 100:
                print(f"  {part[:100]}...")
            else:
                print(f"  {part}")

        if args.dev_test:
            print(f"\nDev-Test loop would run up to {MAX_DEV_TEST_CYCLES} cycles.")
            print(f"Each cycle: Developer agent -> Tester agent -> feedback loop.")

        print("\n--- END DRY RUN ---")
        return

    # Confirm before running
    print(f"\nDescription: {task.get('description', 'No description')[:200]}")
    if not args.yes:
        response = input("\nProceed? (y/n): ").strip().lower()
        if response != "y":
            print("Aborted.")
            return

    # --- Execute ---

    if args.dev_test:
        # Dev+Tester iteration loop (Phase 2)
        print(f"\nStarting Dev+Test loop (max {MAX_DEV_TEST_CYCLES} cycles)...")
        result, cycles, outcome = await run_dev_test_loop(
            task, project_dir, project_context, args,
        )

        # Post-task telemetry (DB update, ForgeSmith recording, quality scoring, reflexion, MemRL)
        task_role = task.get("role") or "developer"
        await _post_task_telemetry(
            task, result, outcome, role=task_role,
            model=get_role_model(task_role, args, task=task),
            max_turns=get_role_turns(task_role, args, task=task),
            cycle_number=cycles,
            dispatch_config=getattr(args, "dispatch_config", None))

        # Optional security review after successful dev-test
        # CLI --security-review flag takes precedence, then dispatch config top-level key,
        # then features.security_review flag (all must agree for review to run)
        dc = getattr(args, "dispatch_config", None) or {}
        security_review_enabled = args.security_review
        if security_review_enabled is None:
            security_review_enabled = dc.get("security_review", False)
        # Feature flag can disable even if top-level key is True
        if not is_feature_enabled(dc, "security_review"):
            security_review_enabled = False

        if security_review_enabled and outcome in ("tests_passed", "no_tests"):
            sec_result = await run_security_review(task, project_dir, project_context, args)


        # Verify the task status in TheForge
        verified, verify_msg = verify_task_updated(task["id"])

        # Print loop summary
        print_dev_test_summary(task, result, cycles, outcome, verified, verify_msg)

    else:
        # Single-agent mode (Phase 1 — with model tiering)
        use_streaming = args.role not in EARLY_TERM_EXEMPT_ROLES
        role_turns_max = get_role_turns(args.role, args, task=task)
        role_model = get_role_model(args.role, args, task=task)
        # Dynamic budget for single-agent mode
        role_turns_allocated, _ = calculate_dynamic_budget(role_turns_max)
        system_prompt = build_system_prompt(
            task, project_context, project_dir, role=args.role,
            dispatch_config=getattr(args, "dispatch_config", None),
            max_turns=role_turns_allocated,
        )
        print(f"Dynamic budget: {role_turns_allocated}/{role_turns_max} turns")
        cmd = build_cli_command(
            system_prompt, project_dir, role_turns_allocated, role_model, role=args.role,
            streaming=use_streaming,
        )
        print(f"System prompt: {len(system_prompt)} chars, ~{estimate_tokens(system_prompt)} tokens")

        print(f"\nStarting {args.role} agent...")
        if use_streaming:
            # Streaming mode with early termination — no retries (kill is intentional)
            result = await run_agent_streaming(cmd, role=args.role)
            attempts = 1
        else:
            result, attempts = await run_agent_with_retries(cmd, task, args.retries)

        # Tag result with dynamic budget info for telemetry
        result["turns_allocated"] = role_turns_allocated
        result["turns_max"] = role_turns_max

        # Determine outcome
        if result.get("early_terminated"):
            single_outcome = "early_terminated"
        elif result["success"]:
            single_outcome = "tests_passed"
        else:
            single_outcome = "developer_failed"

        # Post-task telemetry
        await _post_task_telemetry(
            task, result, single_outcome, role=args.role,
            model=role_model, max_turns=role_turns_max,
            dispatch_config=getattr(args, "dispatch_config", None))

        # Verify the task status in TheForge
        verified, verify_msg = verify_task_updated(task["id"])

        # Print summary
        print_summary(task, result, verified, verify_msg)
        if attempts > 1:
            print(f"  Attempts: {attempts}/{args.retries}")


def main():
    """Entry point that runs the async main.

    For --project mode, loops until no more todo tasks remain.
    For --task/--tasks mode, runs once and exits.
    """
    # Check sys.argv to determine if --project mode (no parse_args needed)
    is_project_mode = "--project" in sys.argv and "--task" not in sys.argv and "--tasks" not in sys.argv

    if is_project_mode:
        # --project mode: loop through all todo tasks
        task_count = 0
        while True:
            try:
                asyncio.run(async_main())
                task_count += 1
                print(f"\n{'='*60}")
                print(f"Task complete ({task_count} so far). Checking for more...")
                print(f"{'='*60}\n")
            except SystemExit as e:
                if e.code == 0:
                    # Normal exit = no more tasks
                    # Extract project name from sys.argv since we don't have parsed args here
                    project_name = ""
                    for i, arg in enumerate(sys.argv):
                        if arg == "--project" and i + 1 < len(sys.argv):
                            project_name = sys.argv[i + 1]
                            break
                    print(f"\nAll done! Completed {task_count} tasks for project {project_name}.")
                    break
                else:
                    # Error exit
                    print(f"\nOrchestrator exited with code {e.code} after {task_count} tasks.")
                    sys.exit(e.code)
            except KeyboardInterrupt:
                print(f"\nInterrupted after {task_count} tasks.")
                sys.exit(0)
            except Exception as e:
                print(f"\nError after {task_count} tasks: {e}")
                print("Stopping orchestrator loop.")
                sys.exit(1)
    else:
        # Single task or parallel tasks mode: run once
        asyncio.run(async_main())


if __name__ == "__main__":
    main()

