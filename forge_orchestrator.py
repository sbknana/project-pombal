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


# --- Untrusted Content Isolation ---
# Per-prompt random delimiter prevents injected content from closing its own
# boundary.  Generated fresh each time a prompt is built so that malicious
# content cannot predict or spoof the marker.  See EQ-24 / EQ-10 / EQ-25.

def _make_untrusted_delimiter():
    """Return a unique, unpredictable delimiter for untrusted content markers."""
    return f"UNTRUSTED_{uuid.uuid4().hex[:8]}"


def wrap_untrusted(content, delimiter):
    """Wrap *content* in unpredictable untrusted-content markers.

    The delimiter is generated once per prompt build and shared across all
    injection sites so the agent sees a single, consistent boundary token.
    """
    return f"<<<{delimiter}>>>\n{content}\n<<<END_{delimiter}>>>"


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


def generate_skill_manifest():
    """Scan all prompt and skill .md files and return a dict of {relative_path: sha256_hex}.

    Used by --regenerate-manifest to create/update skill_manifest.json.
    """
    base_dir = Path(__file__).parent
    manifest = {}

    # Collect all .md files from prompts/ and skills/
    for search_dir in [PROMPTS_DIR, SKILLS_BASE_DIR]:
        if not search_dir.is_dir():
            continue
        for md_file in sorted(search_dir.rglob("*.md")):
            rel_path = str(md_file.relative_to(base_dir))
            file_hash = hashlib.sha256(md_file.read_bytes()).hexdigest()
            manifest[rel_path] = file_hash

    return manifest


def write_skill_manifest():
    """Generate and write skill_manifest.json to the repo root."""
    manifest = generate_skill_manifest()
    manifest_data = {
        "version": 1,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "description": "SHA-256 hashes of prompt and skill files for integrity verification",
        "files": manifest,
    }
    SKILL_MANIFEST_FILE.write_text(
        json.dumps(manifest_data, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {len(manifest)} file hashes to {SKILL_MANIFEST_FILE}")
    return manifest_data


def verify_skill_integrity():
    """Verify all prompt and skill files match known-good SHA-256 hashes.

    Returns True if verification passes (or manifest is missing for backward compat).
    Returns False if any file has been tampered with or is missing.
    """
    if not SKILL_MANIFEST_FILE.exists():
        print("WARNING: skill_manifest.json not found — skipping integrity check "
              "(generate with --regenerate-manifest)")
        return True  # backward compat: missing manifest is not a blocker

    try:
        manifest_data = json.loads(SKILL_MANIFEST_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        print(f"CRITICAL: Failed to load skill_manifest.json: {e}")
        return False

    expected_files = manifest_data.get("files", {})
    if not expected_files:
        print("CRITICAL: skill_manifest.json contains no file entries — refusing to dispatch")
        return False

    base_dir = Path(__file__).parent
    mismatches = []
    missing = []

    for rel_path, expected_hash in expected_files.items():
        file_path = base_dir / rel_path
        if not file_path.exists():
            missing.append(rel_path)
            continue
        actual_hash = hashlib.sha256(file_path.read_bytes()).hexdigest()
        if actual_hash != expected_hash:
            mismatches.append(rel_path)

    if missing:
        print(f"CRITICAL: Skill integrity check FAILED — {len(missing)} file(s) missing:")
        for f in missing:
            print(f"  MISSING: {f}")

    if mismatches:
        print(f"CRITICAL: Skill integrity check FAILED — {len(mismatches)} file(s) modified:")
        for f in mismatches:
            print(f"  TAMPERED: {f}")

    if missing or mismatches:
        print("CRITICAL: Agent dispatch BLOCKED — skill files do not match manifest. "
              "If changes are intentional, run: python forge_orchestrator.py --regenerate-manifest")
        return False

    return True


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


def run_quality_scoring(task, result, outcome, role, output=None, dispatch_config=None):
    """Run post-task quality scoring and store results.

    Called after record_agent_run() on successful outcomes. Extracts
    result_text and FILES_CHANGED from the result dict, scores them,
    and stores scores in rubric_scores.

    Gated by the quality_scoring feature flag. Never crashes the
    orchestrator — all errors are logged and swallowed.
    """
    if not is_feature_enabled(dispatch_config, "quality_scoring"):
        return
    try:
        task_id = task.get("id") if isinstance(task, dict) else task
        project_id = task.get("project_id") if isinstance(task, dict) else None

        agent_run_id = _get_latest_agent_run_id(task_id)
        if not agent_run_id:
            log(f"  [Quality] No agent_run_id found for task {task_id}", output)
            return

        result_text = result.get("result_text", "") if isinstance(result, dict) else ""
        files_changed = parse_developer_output(result_text)

        score_result = quality_score_and_store(
            result_text=result_text,
            files_changed=files_changed,
            role=role,
            agent_run_id=agent_run_id,
            task_id=task_id,
            project_id=project_id,
        )
        if score_result:
            log(f"  [Quality] Scored run {agent_run_id}: "
                f"{score_result['total_score']:.1f}/{score_result['max_possible']:.0f} "
                f"({score_result['normalized_score']:.0%})", output)
    except Exception as e:
        log(f"  [Quality] WARNING: Quality scoring failed: {e}", output)


# --- Reflexion (Post-task self-reflection for learning) ---

# Reflexion prompt — asks for specific, actionable self-reflection
REFLEXION_PROMPT = (
    "Reflect on this task. What approach did you take? What worked? "
    "What did not? What would you do differently next time? "
    "Be specific and concise (3-5 sentences). Reference exact files, "
    "error messages, tools, or strategies."
)

# Initial Q-value for new episodes (neutral prior)
INITIAL_Q_VALUE = 0.5


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


async def run_reflexion_agent(task, result, outcome, role="developer", output=None):
    """Spawn a lightweight agent to generate reflection when not in output.

    This is a fallback — if the agent included REFLECTION: in its
    structured output, we already have it. This function is only called
    when parse_reflection() returned None.

    Uses minimal turns (max 2) and sonnet model to keep cost low.
    The reflection is stored back into the most recent agent_episode.
    """
    try:
        task_id = task.get("id") if isinstance(task, dict) else task
        task_title = task.get("title", "unknown") if isinstance(task, dict) else "unknown"
        result_text = result.get("result_text", "") if isinstance(result, dict) else ""
        num_turns = result.get("num_turns", 0) if isinstance(result, dict) else 0

        # Build a concise context for the reflection agent
        # Use last 1500 chars of output to stay within prompt limits
        output_tail = result_text[-1500:] if len(result_text) > 1500 else result_text

        reflection_prompt = (
            f"You are reflecting on a completed task.\n\n"
            f"Task: #{task_id} - {task_title}\n"
            f"Role: {role}\n"
            f"Outcome: {outcome}\n"
            f"Turns used: {num_turns}\n\n"
            f"Agent output (tail):\n{output_tail}\n\n"
            f"{REFLEXION_PROMPT}\n\n"
            f"Respond with ONLY your reflection text (3-5 sentences). "
            f"No preamble, no formatting, no markdown."
        )

        cmd = [
            "claude",
            "-p", reflection_prompt,
            "--output-format", "json",
            "--model", "sonnet",
            "--max-turns", "2",
            "--no-session-persistence",
        ]

        log(f"  [Reflexion] Spawning reflection agent for task #{task_id}...", output)
        ref_result = await run_agent(cmd, timeout=60)

        if not ref_result.get("success"):
            log(f"  [Reflexion] Reflection agent failed: {ref_result.get('errors', [])}", output)
            return

        reflection_text = ref_result.get("result_text", "").strip()
        if not reflection_text or len(reflection_text) < 20:
            log(f"  [Reflexion] Reflection too short, discarding.", output)
            return

        # Strip any JSON wrapper if present
        try:
            parsed = json.loads(reflection_text)
            if isinstance(parsed, dict) and "result" in parsed:
                reflection_text = parsed["result"].strip()
        except (json.JSONDecodeError, KeyError):
            pass  # not JSON, use raw text

        # Update the most recent episode for this task (subquery for portability)
        conn = get_db_connection(write=True)
        conn.execute(
            """UPDATE agent_episodes SET reflection = ?
               WHERE id = (
                   SELECT id FROM agent_episodes
                   WHERE task_id = ? AND reflection IS NULL
                   ORDER BY id DESC LIMIT 1
               )""",
            (reflection_text, task_id),
        )
        conn.commit()
        conn.close()

        preview = reflection_text[:120] + "..." if len(reflection_text) > 120 else reflection_text
        log(f"  [Reflexion] Captured reflection: {preview}", output)

    except Exception as e:
        log(f"  [Reflexion] WARNING: Standalone reflection failed: {e}", output)


async def maybe_run_reflexion(task, result, outcome, role="developer", output=None):
    """Record episode and optionally spawn reflection agent.

    This is the main entry point for the Reflexion pattern. Call this
    after record_agent_run() at every task completion point.

    Flow:
    1. Record the episode (extracts reflection from output if present)
    2. If no reflection was found in output, spawn lightweight agent
    """
    record_agent_episode(task, result, outcome, role=role, output=output)

    # Check if reflection was captured from the structured output
    result_text = result.get("result_text", "") if isinstance(result, dict) else ""
    if not parse_reflection(result_text):
        await run_reflexion_agent(task, result, outcome, role=role, output=output)


# fetch_task, fetch_next_todo, fetch_project_context, _get_task_status,
# fetch_project_info, fetch_tasks_by_ids extracted to equipa/tasks.py


# --- Prompt Building ---

def build_task_prompt(task, project_context, project_dir, delimiter=None):
    """Build the task-specific instruction block.

    Args:
        delimiter: Unpredictable boundary token from _make_untrusted_delimiter().
            When provided, all database-sourced content is additionally wrapped
            in <<<DELIMITER>>> ... <<<END_DELIMITER>>> markers so agents can
            distinguish data from instructions even if <task-input> tags are
            spoofed by injected content.
    """
    # Task metadata (safe — controlled by orchestrator, not user input)
    lines = [
        "## Assigned Task",
        f"- **Task ID:** {task['id']}",
        f"- **Project:** {task.get('project_name', 'Unknown')} (project_id: {task.get('project_id', '?')})",
        f"- **Priority:** {task.get('priority', 'medium')}",
        f"- **Working Directory:** {project_dir}",
        "",
    ]

    # Helper: wrap content in both task-input tags AND unpredictable delimiter
    def _wrap(tag_type, content):
        inner = wrap_untrusted(content, delimiter) if delimiter else content
        return f'<task-input type="{tag_type}" trust="database">\n{inner}\n</task-input>'

    # Task title and description — from database, could contain injection
    lines.append(_wrap("task-title", task["title"]))
    lines.append("")
    lines.append(_wrap("task-description", task.get("description", "No description provided")))
    lines.append("")

    # Project context also wrapped — comes from database
    session = project_context.get("last_session")
    if session:
        ctx_lines = [f"Last session ({session.get('session_date', 'unknown')}):"]
        ctx_lines.append(session.get("summary", "No summary"))
        if session.get("next_steps"):
            ctx_lines.append(f"Next steps: {session['next_steps']}")
        lines.append("## Recent Project Context")
        lines.append(_wrap("session-context", "\n".join(ctx_lines)))
        lines.append("")

    questions = project_context.get("open_questions", [])
    if questions:
        q_lines = []
        for q in questions:
            q_lines.append(f"- {q['question']}")
            if q.get("context"):
                q_lines.append(f"  Context: {q['context']}")
        lines.append("## Open Questions (unresolved)")
        lines.append(_wrap("open-questions", "\n".join(q_lines)))
        lines.append("")

    decisions = project_context.get("recent_decisions", [])
    if decisions:
        d_lines = []
        for d in decisions:
            d_lines.append(f"- {d['decision']} ({d.get('decided_at', 'unknown')})")
            if d.get("rationale"):
                d_lines.append(f"  Rationale: {d['rationale']}")
        lines.append("## Recent Decisions")
        lines.append(_wrap("decisions", "\n".join(d_lines)))
        lines.append("")

    return "\n".join(lines)


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

# Track which prompt version was used per role (for A/B testing telemetry).
# Set by build_system_prompt(), read by record_agent_run().
_last_prompt_version = {}


def build_system_prompt(task, project_context, project_dir, role="developer",
                        extra_context="", dispatch_config=None, error_type=None,
                        max_turns=None):
    """Read _common.md + role prompt, replace placeholders, append task prompt.

    Applies context engineering principles:
    - Token budget management (8K target, trimming in priority order)
    - Lesson deduplication (60%+ word overlap removed, max 5)
    - Episode relevance scoring (keyword overlap + recency weighting)
    - Token count logging per dispatch
    - A/B prompt version selection (GEPA-evolved prompts)
    - Budget visibility (max_turns info injected into prompt)

    extra_context: optional string appended after the task prompt (used for
    compaction history and test failure feedback in dev-test loop).
    dispatch_config: optional config dict for task-type-specific prompt injection.
    error_type: optional error type to filter relevant lessons (e.g. 'timeout', 'max_turns').
    max_turns: optional int — the turn budget allocated for this agent run.
        When provided, a budget visibility line is injected into the prompt so
        the agent can make rational decisions about depth vs breadth.

    Returns the system prompt string. Also sets _last_prompt_version[role] for
    telemetry tracking.
    """
    common_path = PROMPTS_DIR / "_common.md"
    role_path = ROLE_PROMPTS.get(role)

    if not role_path:
        print(f"ERROR: Unknown role '{role}'. Available: {', '.join(ROLE_PROMPTS.keys())}")
        sys.exit(1)

    if not common_path.exists():
        print(f"ERROR: Common prompt not found at {common_path}")
        sys.exit(1)

    if not role_path.exists():
        print(f"ERROR: Role prompt not found at {role_path}")
        sys.exit(1)

    # A/B prompt version selection: try GEPA-evolved prompt if available
    # Gated by gepa_ab_testing feature flag
    prompt_version = "baseline"
    if is_feature_enabled(dispatch_config, "gepa_ab_testing"):
        try:
            from forgesmith_gepa import get_ab_prompt_for_role
            selected_path, prompt_version = get_ab_prompt_for_role(role)
            if selected_path.exists() and prompt_version != "baseline":
                role_path = selected_path
        except ImportError:
            pass  # forgesmith_gepa not available, use baseline

    # Track which version was used for telemetry
    _last_prompt_version[role] = prompt_version

    # Generate a per-prompt unpredictable delimiter for untrusted content
    # isolation.  This prevents injected content from spoofing or closing
    # its own boundary markers (addresses EQ-24, EQ-10, EQ-25).
    _untrusted_delimiter = _make_untrusted_delimiter()

    # Build prompt: common rules + role-specific prompt (never trimmed)
    common_text = common_path.read_text(encoding="utf-8")
    role_text = role_path.read_text(encoding="utf-8")
    template = common_text + "\n\n---\n\n" + role_text

    # Replace placeholders
    prompt = template.replace("{task_id}", str(task["id"]))
    prompt = prompt.replace("{project_id}", str(task.get("project_id", "")))

    # --- Lesson injection with deduplication ---
    # Gated by forgesmith_lessons feature flag
    if is_feature_enabled(dispatch_config, "forgesmith_lessons"):
        # Fetch more candidates than we'll inject, then deduplicate
        lessons = get_relevant_lessons(role=role, error_type=error_type, limit=10)
        if lessons:
            # Deduplicate: remove 60%+ word overlap, cap at 5
            lessons = deduplicate_lessons(lessons)
            lessons_text = format_lessons_for_injection(lessons, delimiter=_untrusted_delimiter)
            prompt = prompt + "\n\n" + lessons_text
            # Update times_injected counter for each lesson
            update_lesson_injection_count([l["id"] for l in lessons])

    # --- Episode injection with relevance scoring ---
    # Gated by forgesmith_episodes feature flag
    task_id = task.get("id") if isinstance(task, dict) else task
    project_id = task.get("project_id") if isinstance(task, dict) else None
    task_type = task.get("task_type", "feature") if isinstance(task, dict) else None
    task_description = task.get("description", "") if isinstance(task, dict) else ""

    if is_feature_enabled(dispatch_config, "forgesmith_episodes"):
        # Check token budget to decide episode limit
        current_tokens = estimate_tokens(prompt)
        episode_limit = 3
        if current_tokens > EPISODE_REDUCTION_THRESHOLD:
            episode_limit = 2  # Reduce episodes when prompt is already large

        if project_id:
            episodes = get_relevant_episodes(
                role=role, project_id=project_id, task_type=task_type,
                min_q_value=0.3, limit=episode_limit,
                task_description=task_description,
            )
            if episodes:
                episodes_text = format_episodes_for_injection(episodes, delimiter=_untrusted_delimiter)
                prompt = prompt + "\n\n" + episodes_text
                # Track injected episode IDs for q-value updates after task completion
                ep_ids = [ep["id"] for ep in episodes]
                _injected_episodes_by_task[task_id] = ep_ids
                update_episode_injection_count(ep_ids)

    # Inject task-type-specific guidance if available
    task_type_supplement = ""
    if dispatch_config and "task_type_prompts" in dispatch_config:
        task_type = task.get("task_type", "feature") or "feature"
        task_type_prompts = dispatch_config["task_type_prompts"]
        if task_type in task_type_prompts:
            task_type_supplement = (
                f"\n\n## Task Type Guidance ({task_type})\n\n"
                f"{task_type_prompts[task_type]}\n"
            )

    # Append task-specific instructions (never trimmed)
    task_prompt = build_task_prompt(task, project_context, project_dir, delimiter=_untrusted_delimiter)
    prompt = prompt + "\n\n---\n\n" + task_prompt

    # Append task-type supplement after task prompt
    if task_type_supplement:
        prompt = prompt + task_type_supplement

    # --- Language-specific prompt injection ---
    # Detect project language and load corresponding guidance if available
    # Gated by language_prompts feature flag
    if project_dir and is_feature_enabled(dispatch_config, "language_prompts"):
        lang_info = detect_project_language(project_dir)
        lang_prompts_dir = PROMPTS_DIR / "languages"
        injected_langs = set()
        for lang_key in lang_info.get("languages", []):
            lang_prompt_path = lang_prompts_dir / f"{lang_key}.md"
            if lang_prompt_path.exists() and lang_key not in injected_langs:
                try:
                    lang_text = lang_prompt_path.read_text(encoding="utf-8")
                    frameworks_note = ""
                    if lang_info.get("frameworks"):
                        detected = [f for f in lang_info["frameworks"]
                                    if f not in ("dotnet", "maven", "gradle")]
                        if detected:
                            frameworks_note = (
                                f"\n\nDetected frameworks: {', '.join(detected)}. "
                                f"Apply framework-specific patterns where relevant."
                            )
                    prompt = prompt + "\n\n" + lang_text + frameworks_note
                    injected_langs.add(lang_key)
                except OSError:
                    pass  # File read failed, skip silently

    # Budget visibility: tell the agent how many turns it has
    if max_turns and max_turns > 0:
        prompt = prompt + (
            f"\n\nYou have {max_turns} turns for this task. "
            f"The orchestrator will log budget updates every "
            f"{BUDGET_CHECK_INTERVAL} turns."
        )

    # Append extra context (compaction history, test failures) if provided
    if extra_context:
        prompt = prompt + "\n\n---\n\n" + extra_context

    # --- Token budget enforcement ---
    # Trim in priority order: old episodes first, then generic lessons
    # Never trim: role prompt, task description
    token_count = estimate_tokens(prompt)

    if token_count > SYSTEM_PROMPT_TOKEN_TARGET:
        # Priority 1: Trim old episodes (## Past Experience)
        if token_count > SYSTEM_PROMPT_TOKEN_TARGET:
            prompt = _trim_prompt_section(prompt, "## Past Experience",
                                          max_chars=CHARS_PER_TOKEN * 500)
            token_count = estimate_tokens(prompt)

        # Priority 2: Trim generic lessons (## Lessons from Previous Runs)
        if token_count > SYSTEM_PROMPT_TOKEN_HARD_LIMIT:
            prompt = _trim_prompt_section(prompt, "## Lessons from Previous Runs",
                                          max_chars=CHARS_PER_TOKEN * 300)
            token_count = estimate_tokens(prompt)

        # Priority 3: Trim extra context (## Prior Work Summary, etc.)
        if token_count > SYSTEM_PROMPT_TOKEN_HARD_LIMIT:
            prompt = _trim_prompt_section(prompt, "## Prior Work Summary",
                                          max_chars=CHARS_PER_TOKEN * 400)
            token_count = estimate_tokens(prompt)

    # Log token count for monitoring
    final_tokens = estimate_tokens(prompt)
    budget_status = "OK" if final_tokens <= SYSTEM_PROMPT_TOKEN_TARGET else "OVER"
    print(f"  [ContextEng] System prompt: {len(prompt)} chars, ~{final_tokens} tokens "
          f"({budget_status}, target: {SYSTEM_PROMPT_TOKEN_TARGET})")

    return prompt


# get_task_complexity extracted to equipa/tasks.py
# get_role_turns, get_role_model extracted to equipa/roles.py


# --- Checkpoint/Resume ---
# save_checkpoint, load_checkpoint, clear_checkpoints extracted to equipa/checkpoints.py


def build_checkpoint_context(checkpoint_text, attempt):
    """Build context string from a checkpoint for the next agent attempt.

    Uses compact_agent_output() to extract structured data (RESULT, FILES_CHANGED,
    BLOCKERS, SUMMARY) instead of passing raw text, preventing context rot.
    """
    # Compact checkpoint to structured summary (max 200 words)
    compacted = compact_agent_output(checkpoint_text, max_words=200)

    return (
        f"## Previous Attempt (#{attempt}) — Continue From Here\n\n"
        f"**The previous agent ran out of turns. Start writing code IMMEDIATELY — "
        f"do not repeat the same research.**\n\n"
        f"**The previous agent FAILED because it spent all its time reading instead "
        f"of writing code. DO NOT make the same mistake. You are the replacement.**\n\n"
        f"Start writing code IMMEDIATELY. Your FIRST tool call must be Edit or Write — "
        f"not Read, not Glob, not Grep. You have the previous agent's summary below. "
        f"Use it to skip exploration entirely and go straight to implementation.\n\n"
        f"### Previous Agent Summary:\n"
        f"<task-input type=\"checkpoint\" trust=\"agent-output\">\n{compacted}\n</task-input>\n\n"
        f"**CRITICAL:** Do NOT repeat the previous agent's exploration. Do NOT re-read "
        f"files they already read. Do NOT analyze the codebase from scratch. Look at "
        f"what remains to be done and START CODING in your FIRST turn.\n\n"
        f"**You are a SENIOR engineer. Make decisions. Write code. Ship it.** "
        f"The orchestrator is watching — another failure means this task gets "
        f"permanently blocked and escalated to a human. Do not be the agent that "
        f"causes escalation."
    )


# --- CLI Command Building ---

def build_cli_command(system_prompt, project_dir, max_turns, model, role="developer",
                      streaming=False):
    """Build the claude CLI command as a list of arguments.

    Args:
        streaming: If True, use stream-json output format for real-time monitoring.
    """
    output_format = "stream-json" if streaming else "json"
    cmd = [
        "claude",
        "-p",
        f"Execute the task described in your system prompt. Work in: {project_dir}",
        "--output-format", output_format,
        "--model", model,
        "--max-turns", str(max_turns),
        "--no-session-persistence",
        "--append-system-prompt", system_prompt,
        "--mcp-config", str(MCP_CONFIG),
        "--add-dir", str(project_dir),
        "--permission-mode", "bypassPermissions",
    ]

    # stream-json requires --verbose
    if streaming:
        cmd.append("--verbose")

    # Load role-specific skills directory if it exists
    skills_dir = ROLE_SKILLS.get(role)
    if skills_dir and skills_dir.exists():
        cmd.extend(["--add-dir", str(skills_dir)])

    return cmd


# --- Agent Execution ---

async def run_agent(cmd, timeout=None):
    """Spawn claude -p, capture output, handle timeout."""
    effective_timeout = timeout or PROCESS_TIMEOUT
    start_time = time.time()

    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                process.communicate(),
                timeout=effective_timeout,
            )
        except asyncio.TimeoutError:
            # Try to capture any partial output before killing
            process.kill()
            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    process.communicate(), timeout=5,
                )
                partial_text = stdout_bytes.decode("utf-8", errors="replace").strip()
            except Exception:
                partial_text = ""
            duration = time.time() - start_time
            return {
                "success": False,
                "result_text": partial_text,
                "num_turns": 0,
                "duration": duration,
                "cost": None,
                "errors": [f"Process timed out after {effective_timeout} seconds"],
            }

    except FileNotFoundError:
        return {
            "success": False,
            "result_text": "",
            "num_turns": 0,
            "duration": 0,
            "cost": None,
            "errors": ["'claude' command not found. Is Claude Code installed and on PATH?"],
        }

    duration = time.time() - start_time
    stdout_text = stdout_bytes.decode("utf-8", errors="replace").strip()
    stderr_text = stderr_bytes.decode("utf-8", errors="replace").strip()

    # Parse JSON output
    result = {
        "success": False,
        "result_text": stdout_text,
        "num_turns": 0,
        "duration": duration,
        "cost": None,
        "errors": [],
    }

    if stderr_text:
        result["errors"].append(f"stderr: {stderr_text}")

    if not stdout_text:
        result["errors"].append("No output from agent")
        return result

    try:
        data = json.loads(stdout_text)
        result["result_text"] = data.get("result", stdout_text)
        result["num_turns"] = data.get("num_turns", 0)
        result["cost"] = data.get("cost_usd")

        # Check for error subtypes
        subtype = data.get("subtype", "")
        if subtype == "error_max_turns":
            # Agent ran out of turns but may have done useful work
            result["success"] = True
            result["errors"].append("Agent hit max turns limit")
        elif data.get("is_error"):
            result["success"] = False
            result["errors"].append(f"Agent error: {data.get('result', 'unknown')}")
        else:
            result["success"] = True

    except json.JSONDecodeError:
        # Output wasn't JSON, treat raw text as result
        result["result_text"] = stdout_text
        result["success"] = process.returncode == 0

    return result


# --- Early Termination (Stuck Agent Detection) ---

# _check_stuck_phrases, _check_monologue extracted to equipa/monitoring.py


# _get_budget_message, _check_cost_limit, _check_git_changes,
# _parse_early_complete, _compute_output_hash, _TOOL_SIG_KEY,
# _build_tool_signature, _detect_tool_loop,
# _build_streaming_result extracted to equipa/monitoring.py

async def run_agent_streaming(cmd, role="developer", timeout=None, output=None,
                              max_turns=None, task_id=None, run_id=None,
                              cycle_number=1, project_dir=None):
    """Spawn claude -p with stream-json output for real-time stuck detection.

    Monitors agent output turn-by-turn and terminates early if stuck signals
    are detected. Only applies file-change monitoring to non-exempt roles
    (developer, tester, debugger, etc.).

    When task_id is provided, per-tool actions are logged to the agent_actions
    table for observability and ForgeSmith analysis.

    Returns the same dict format as run_agent().
    """
    effective_timeout = timeout or PROCESS_TIMEOUT
    start_time = time.time()
    is_exempt = role in EARLY_TERM_EXEMPT_ROLES

    # Tracking state
    turn_count = 0
    turns_without_file_change = 0
    # Scale early termination with budget — larger budgets get more reading time
    # but never exceed 2x the base threshold (prevents overly generous scaling)
    effective_kill_turns = min(
        EARLY_TERM_KILL_TURNS * 2,
        max(EARLY_TERM_KILL_TURNS, int((max_turns or EARLY_TERM_KILL_TURNS) * 0.4))
    )
    effective_final_warn_turns = max(EARLY_TERM_FINAL_WARN_TURNS, int(effective_kill_turns * 0.8))
    effective_warn_turns = max(EARLY_TERM_WARN_TURNS, int(effective_kill_turns * 0.5))
    has_any_file_change = False
    tool_history = []          # list of "tool_name:key_input" strings
    tool_errors = []           # list of error strings (None if success, string if error)
    tool_output_hashes = []    # list of SHA256 hashes of tool result content
    action_log = []            # per-tool action entries for agent_actions table
    stuck_phrase_count = 0
    consecutive_text_only_turns = 0  # monologue detection: text-only assistant messages
    monologue_warning_injected = False  # track if we've warned about monologue
    all_text_chunks = []       # accumulate assistant text for final result
    result_data = None         # the final "result" message from stream-json
    warning_injected = False
    final_warning_injected = False  # track if final warning has been injected
    loop_warning_injected = False  # track if we've warned about loop detection
    early_term_reason = None
    loop_detected_details = None  # store loop details for error_summary
    agent_signaled_done = False    # agent-initiated early completion (EARLY_COMPLETE:)
    early_complete_reason = None   # reason provided by agent for early completion

    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            limit=4 * 1024 * 1024,  # 4MB buffer for large file reads
        )
    except FileNotFoundError:
        return {
            "success": False,
            "result_text": "",
            "num_turns": 0,
            "duration": 0,
            "cost": None,
            "errors": ["'claude' command not found. Is Claude Code installed and on PATH?"],
        }

    try:
        # Read stdout line-by-line with overall timeout
        while True:
            elapsed = time.time() - start_time
            remaining = effective_timeout - elapsed
            if remaining <= 0:
                early_term_reason = f"Process timed out after {effective_timeout} seconds"
                break

            try:
                line_bytes = await asyncio.wait_for(
                    process.stdout.readline(),
                    timeout=min(remaining, 600),  # per-line wait (600s for large writes, bumped from 300)
                )
            except asyncio.TimeoutError:
                early_term_reason = f"No output for 600s (overall timeout: {effective_timeout}s)"
                break

            if not line_bytes:
                # EOF — process finished
                break

            line = line_bytes.decode("utf-8", errors="replace").strip()
            if not line:
                continue

            # Parse stream-json message
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue

            msg_type = msg.get("type", "")

            # --- Handle "result" message (final) ---
            if msg_type == "result":
                result_data = msg
                break

            # --- Handle "assistant" messages (agent turns) ---
            if msg_type == "assistant":
                message = msg.get("message", {})
                content_blocks = message.get("content", [])

                # Track whether THIS assistant message contains any file changes
                # (an assistant message = one API turn, may contain multiple tool calls)
                turn_has_file_change = False
                turn_has_tool_calls = False

                for block in content_blocks:
                    block_type = block.get("type", "")

                    if block_type == "text":
                        text = block.get("text", "")
                        all_text_chunks.append(text)

                        # Check for agent-initiated early completion signal
                        ec_reason = _parse_early_complete(text)
                        if ec_reason and not agent_signaled_done:
                            agent_signaled_done = True
                            early_complete_reason = ec_reason
                            log(f"  [EarlyComplete] Agent signaled done at turn "
                                f"~{turn_count}: {ec_reason}", output)
                            # Do NOT break here — let the current assistant
                            # message finish (all content blocks processed)

                        # Check for stuck phrases
                        matched = _check_stuck_phrases(text)
                        if matched:
                            stuck_phrase_count += 1
                            log(f"  [EarlyTerm] Stuck signal detected at turn ~{turn_count}: "
                                f"\"{matched}\" (count: {stuck_phrase_count})", output)
                            # 3 stuck phrases = terminate
                            if stuck_phrase_count >= 3:
                                early_term_reason = (
                                    f"Agent stuck: repeated stuck phrases "
                                    f"({stuck_phrase_count}x, last: \"{matched}\")"
                                )

                    elif block_type == "tool_use":
                        tool_name = block.get("name", "")
                        tool_input = block.get("input", {})
                        turn_count += 1
                        turn_has_tool_calls = True

                        # Record action entry for action logging
                        try:
                            input_str = json.dumps(tool_input, default=str)
                        except (TypeError, ValueError):
                            input_str = str(tool_input)
                        action_log.append({
                            "turn": turn_count,
                            "tool": tool_name,
                            "input_preview": input_str[:200],
                            "input_hash": hashlib.sha256(
                                input_str.encode("utf-8", errors="replace")
                            ).hexdigest(),
                            "timestamp": time.time(),
                        })

                        # Track file-modifying tools
                        if tool_name in ("Edit", "Write", "NotebookEdit"):
                            turn_has_file_change = True
                            has_any_file_change = True
                        elif tool_name == "Bash":
                            # Bash commands that create/modify files count too
                            cmd = tool_input.get("command", "")
                            if any(kw in cmd for kw in [
                                "git commit", "git add", "go build", "npm run build",
                                "mkdir", "cp ", "mv ", "touch ", "tee ", "> ",
                            ]):
                                turn_has_file_change = True
                                has_any_file_change = True

                # After processing all blocks in this assistant message,
                # update the file-change counter ONCE per API turn (not per tool call)
                if turn_has_tool_calls and not is_exempt:
                    if turn_has_file_change:
                        turns_without_file_change = 0
                    else:
                        turns_without_file_change += 1

                        tool_history.append(_build_tool_signature(tool_name, tool_input))

                        # Check for loop detection (repeated failing operations)
                        action, count, last_sig = _detect_tool_loop(
                            tool_history,
                            tool_errors,
                            warn_threshold=LOOP_WARNING_THRESHOLD,
                            terminate_threshold=LOOP_TERMINATE_THRESHOLD,
                            tool_output_hashes=tool_output_hashes,
                        )

                        if action == "terminate":
                            early_term_reason = (
                                f"Loop detected: agent repeated the same operation "
                                f"{count} times ({tool_name})"
                            )
                            log(f"  [LoopDetect] {early_term_reason}", output)
                        elif action == "warn" and not loop_warning_injected:
                            log(f"  [LoopDetect] WARNING: Repeated operation detected "
                                f"({count}x: {tool_name}). Try a different approach.", output)
                            loop_warning_injected = True

                        # File-change turn monitoring (non-exempt roles only)
                        # Escalating warnings: first warning → final warning → kill
                        if not is_exempt and turns_without_file_change > 0:
                            if (turns_without_file_change >= effective_warn_turns
                                    and not warning_injected):
                                log(f"  [EarlyTerm] WARNING: {turns_without_file_change} "
                                    f"turns without file changes (role={role}, "
                                    f"turn ~{turn_count}). WARNING: You have not "
                                    f"written any code yet. Your job is to WRITE "
                                    f"CODE, not read the entire codebase. Start "
                                    f"writing NOW or you will be replaced.", output)
                                warning_injected = True

                            if (turns_without_file_change >= effective_final_warn_turns
                                    and not final_warning_injected):
                                log(f"  [EarlyTerm] FINAL WARNING: "
                                    f"{turns_without_file_change} turns without file "
                                    f"changes (role={role}, turn ~{turn_count}). "
                                    f"FINAL WARNING: You are about to be TERMINATED "
                                    f"for wasting budget. Write code in the NEXT "
                                    f"TURN or a new agent takes over. Do NOT read "
                                    f"another file. Kill threshold: "
                                    f"{effective_kill_turns}.", output)
                                final_warning_injected = True

                            if turns_without_file_change >= effective_kill_turns:
                                early_term_reason = (
                                    f"Agent terminated: {turns_without_file_change} "
                                    f"consecutive turns without file changes. "
                                    f"Agent spent all turns reading instead of "
                                    f"writing code — replaced with stricter agent"
                                )
                                log(f"  [EarlyTerm] KILLED: {early_term_reason}",
                                    output)

                # Budget visibility: log remaining budget at intervals
                if turn_has_tool_calls and max_turns:
                    budget_msg = _get_budget_message(turn_count, max_turns)
                    if budget_msg:
                        log(f"  [Budget] {budget_msg}", output)

                # Monologue detection: track consecutive text-only assistant turns
                if turn_has_tool_calls:
                    consecutive_text_only_turns = 0
                else:
                    consecutive_text_only_turns += 1
                    monologue_action = _check_monologue(
                        consecutive_text_only_turns, turn_count,
                    )
                    if monologue_action == "terminate":
                        early_term_reason = (
                            f"Agent monologue: {consecutive_text_only_turns} "
                            f"consecutive text-only messages without tool use"
                        )
                        log(f"  [Monologue] {early_term_reason}", output)
                    elif (monologue_action == "warn"
                            and not monologue_warning_injected):
                        log(f"  [Monologue] WARNING: {consecutive_text_only_turns} "
                            f"consecutive text-only turns (role={role}, "
                            f"turn ~{turn_count}). Agent may be stuck reasoning "
                            f"without acting.", output)
                        monologue_warning_injected = True

                # If we found a reason to terminate, break out
                if early_term_reason:
                    break

                # If agent signaled early completion, break after this
                # assistant message is fully processed (all content blocks done)
                if agent_signaled_done:
                    log(f"  [EarlyComplete] Current message processed, "
                        f"stopping stream.", output)
                    break

            # --- Handle "user" messages (tool results) ---
            elif msg_type == "user":
                message = msg.get("message", {})
                content_blocks = message.get("content", [])

                for block in content_blocks:
                    block_type = block.get("type", "")

                    if block_type == "tool_result":
                        # Track whether this tool call resulted in an error
                        is_error = block.get("is_error", False)
                        content = block.get("content", "")

                        # Extract error message if present
                        error_text = None
                        if is_error:
                            # Content can be a string or a list of content blocks
                            if isinstance(content, str):
                                error_text = content[:200]  # truncate long errors
                            elif isinstance(content, list):
                                # Extract text from content blocks
                                texts = []
                                for c in content:
                                    if isinstance(c, dict) and c.get("type") == "text":
                                        texts.append(c.get("text", ""))
                                if texts:
                                    error_text = " ".join(texts)[:200]

                        tool_errors.append(error_text)

                        # Compute output hash for loop detection
                        output_hash = _compute_output_hash(content)
                        tool_output_hashes.append(output_hash)

                        # Update the most recent action_log entry with result
                        if action_log:
                            entry = action_log[-1]
                            # Compute output length from content
                            if isinstance(content, str):
                                result_len = len(content)
                            elif isinstance(content, list):
                                result_len = sum(
                                    len(c.get("text", ""))
                                    for c in content
                                    if isinstance(c, dict)
                                )
                            else:
                                result_len = 0
                            entry["success"] = not is_error
                            entry["output_length"] = result_len
                            entry["output_hash"] = output_hash
                            entry["duration_ms"] = int(
                                (time.time() - entry.get("timestamp", time.time())) * 1000
                            )
                            if is_error and error_text:
                                entry["error_type"] = classify_error(error_text)
                                entry["error_summary"] = error_text[:200]

                            # After any tool completes, check git for file changes.
                            # This catches file modifications invisible to tool-name detection:
                            # Bash (rm, sed, echo >), MCP tools (image generation via
                            # DALL-E/Flux/Gemini), or any future tool that writes files.
                            # Note: tool_result arrives AFTER the assistant turn counter was
                            # already updated, so we reset turns_without_file_change directly.
                            if project_dir:
                                if _check_git_changes(project_dir):
                                    has_any_file_change = True
                                    turns_without_file_change = 0
                                    tool_label = entry.get("tool", "unknown")
                                    log(f"  [FileDetect] Git detected file changes "
                                        f"via {tool_label}", output)

    except Exception as e:
        early_term_reason = f"Streaming monitor error: {e}"

    # --- Kill process if still running ---
    if process.returncode is None:
        log(f"  [EarlyTerm] Killing agent process (reason: {early_term_reason})", output)
        process.kill()
        try:
            await asyncio.wait_for(process.communicate(), timeout=5)
        except Exception:
            pass

    duration = time.time() - start_time

    result = _build_streaming_result(
        turn_count, duration, has_any_file_change,
        early_term_reason, agent_signaled_done,
        early_complete_reason, result_data, all_text_chunks)

    # Read any remaining stderr
    try:
        stderr_bytes = await asyncio.wait_for(process.stderr.read(), timeout=2)
        stderr_text = stderr_bytes.decode("utf-8", errors="replace").strip()
        if stderr_text:
            result["errors"].append(f"stderr: {stderr_text}")
    except Exception:
        pass

    # Bulk insert action log to agent_actions table
    if task_id and action_log:
        bulk_log_agent_actions(action_log, task_id, run_id, cycle_number, role)

    # Attach action_log to result for caller inspection
    result["action_log"] = action_log

    return result


# --- Circuit Breakers ---

# validate_output extracted to equipa/parsing.py


async def run_agent_with_retries(cmd, task, max_retries):
    """Run agent with retry logic on failure.

    Returns (result, attempt_number) tuple.
    """
    for attempt in range(1, max_retries + 1):
        if attempt > 1:
            print(f"\n--- Retry {attempt}/{max_retries} ---")

        result = await run_agent(cmd)

        # Check if output is valid
        is_valid, reason = validate_output(result)

        if is_valid:
            return result, attempt

        print(f"  Attempt {attempt} failed: {reason}")

        # Check if the agent updated the task to blocked — that's intentional, not a failure
        verified, _ = verify_task_updated(task["id"])
        if verified:
            return result, attempt

        # Don't retry on timeout — the task is probably too complex
        if any("timed out" in e for e in result.get("errors", [])):
            print("  Not retrying: process timed out")
            return result, attempt

    print(f"\n  All {max_retries} attempts failed.")
    return result, max_retries


# --- Output Parsers (Phase 2) ---
# _parse_structured_output, _TESTER_SCHEMA, _DEVELOPER_FILES_SCHEMA,
# parse_tester_output, parse_developer_output extracted to equipa/parsing.py


# --- Session Compaction (Phase 2) ---

# build_compaction_summary, build_test_failure_context extracted to equipa/parsing.py

    return "\n".join(lines)


async def _run_install_cmd(cmd, cwd, label, output=None):
    """Run an install command, log result. Returns True on success."""
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, cwd=cwd,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode == 0:
            log(f"  [Auto-Install] {label} installed successfully.", output)
            return True
        err = stderr.decode("utf-8", errors="replace")[:200]
        log(f"  [Auto-Install] {label} failed (rc={proc.returncode}): {err}", output)
    except FileNotFoundError:
        log(f"  [Auto-Install] {cmd[0]} not found. Skipping {label}.", output)
    except Exception as e:
        log(f"  [Auto-Install] {label} error: {e}", output)
    return False


async def auto_install_dependencies(project_dir, output=None):
    """Auto-install project dependencies if manifest exists but deps are missing."""
    pdir = Path(project_dir)

    # Python: pyproject.toml or requirements.txt without venv
    has_pyproject = (pdir / "pyproject.toml").exists()
    has_requirements = (pdir / "requirements.txt").exists()
    has_venv = (pdir / "venv").exists() or (pdir / ".venv").exists()

    if (has_pyproject or has_requirements) and not has_venv:
        log(f"  [Auto-Install] Python project without venv detected. Installing...", output)
        venv_path = pdir / "venv"
        await _run_install_cmd(
            [sys.executable, "-m", "venv", str(venv_path)], str(pdir), "Python venv", output)
        pip_path = venv_path / "bin" / "pip"
        if not pip_path.exists():
            pip_path = venv_path / "Scripts" / "pip"
        install_cmd = ([str(pip_path), "install", "-e", f"{project_dir}[dev]"]
                       if has_pyproject
                       else [str(pip_path), "install", "-r", str(pdir / "requirements.txt")])
        await _run_install_cmd(install_cmd, str(pdir), "Python deps", output)

    # Node.js: package.json without node_modules
    if (pdir / "package.json").exists() and not (pdir / "node_modules").exists():
        log(f"  [Auto-Install] Node.js project without node_modules detected. Installing...", output)
        await _run_install_cmd(["npm", "install"], str(pdir), "Node.js deps", output)

    # Go: go.mod present
    if (pdir / "go.mod").exists():
        log(f"  [Auto-Install] Go project detected. Running go mod download...", output)
        await _run_install_cmd(["go", "mod", "download"], str(pdir), "Go modules", output)


def _resolve_build_command(project_dir):
    """Resolve language and build command for a project directory.

    Returns (language: str, build_cmd: list | None, skip_reason: str | None).
    """
    pdir = Path(project_dir)

    if (pdir / "package.json").exists():
        cmd = (["npx", "tsc", "--noEmit"] if (pdir / "tsconfig.json").exists()
               else ["npm", "run", "build"])
        return "node", cmd, None
    if (pdir / "go.mod").exists():
        return "go", ["go", "build", "./..."], None
    if (pdir / "pyproject.toml").exists() or (pdir / "requirements.txt").exists():
        for entry in ("main.py", "app.py"):
            if (pdir / entry).exists():
                return "python", ["python3", "-m", "py_compile", str(pdir / entry)], None
        return "python", None, "no Python entry point found"
    csproj = list(pdir.glob("*.csproj"))
    if csproj:
        return "csharp", ["dotnet", "build", str(csproj[0]), "--no-restore"], None
    return "unknown", None, "no recognized project files"


async def preflight_build_check(project_dir, task_description=None, output=None):
    """Run a lightweight build check before the developer agent starts.

    Returns (success: bool, language: str, error_details: str).
    """
    # Skip if task description mentions build-fix keywords
    if task_description:
        desc_lower = task_description.lower()
        for keyword in PREFLIGHT_SKIP_KEYWORDS:
            if keyword in desc_lower:
                log(f"  [Preflight] Skipped — task description contains '{keyword}' "
                    f"(task is likely to fix the build)", output)
                return (True, "unknown", f"Skipped: task description contains '{keyword}'")

    language, build_cmd, skip_reason = _resolve_build_command(project_dir)
    if not build_cmd:
        msg = skip_reason or ""
        if msg:
            log(f"  [Preflight] {language} project: {msg}. Skipping build check.", output)
        return (True, language, f"Skipped: {msg}" if msg else "")

    log(f"  [Preflight] Detected {language} project. Running build check: {' '.join(build_cmd)}", output)
    try:
        proc = await asyncio.create_subprocess_exec(
            *build_cmd, cwd=str(Path(project_dir)),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=PREFLIGHT_TIMEOUT)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            error_msg = f"Build check timed out after {PREFLIGHT_TIMEOUT}s"
            log(f"  [Preflight] TIMEOUT: {error_msg}", output)
            return (False, language, error_msg)

        if proc.returncode == 0:
            log(f"  [Preflight] Build check passed ({language}).", output)
            return (True, language, "")

        combined = (stderr.decode("utf-8", errors="replace") + "\n"
                    + stdout.decode("utf-8", errors="replace")).strip()
        if len(combined) > 1000:
            combined = combined[:1000] + "\n... (truncated)"
        log(f"  [Preflight] Build FAILED ({language}, rc={proc.returncode}). "
            f"Error preview: {combined[:200]}", output)
        return (False, language, combined)

    except FileNotFoundError:
        error_msg = f"Build tool not found for {language}: {build_cmd[0]}"
        log(f"  [Preflight] {error_msg}. Skipping build check.", output)
        return (True, language, f"Skipped: {error_msg}")
    except Exception as e:
        error_msg = f"Preflight error: {e}"
        log(f"  [Preflight] {error_msg}. Continuing without build check.", output)
        return (True, language, f"Skipped: {error_msg}")


# --- Auto-Fix Build Failure ---

async def _dispatch_autofix_agent(role, task_dict, project_dir, project_context,
                                  budget, task_id, cycle, args, output=None):
    """Dispatch a single auto-fix agent (debugger or planner). Returns (result, cost)."""
    dispatch_config = getattr(args, "dispatch_config", None) if args else None
    model = get_role_model(role, args, task=task_dict)
    streaming = role != "planner"
    prompt = build_system_prompt(
        task_dict, project_context, project_dir,
        role=role, max_turns=budget, dispatch_config=dispatch_config,
    )
    cmd = build_cli_command(prompt, project_dir, budget, model, role=role, streaming=streaming)
    result = await dispatch_agent(
        cmd, role=role, output=output, max_turns=budget, task_id=task_id,
        cycle=cycle, system_prompt=prompt, project_dir=project_dir, args=args,
    )
    cost = result.get("cost") or (result.get("num_turns", 0) * COST_ESTIMATE_PER_TURN)
    return result, cost


async def _handle_preflight_failure(task, project_dir, project_context,
                                    preflight_lang, preflight_error, args,
                                    output=None):
    """Auto-dispatch debugger agent to fix a broken build before the main task.

    Strategy: debugger attempts → planner analysis → guided debugger → give up.
    Returns (fixed: bool, cost: float, summary: str).
    """
    task_id = task["id"]
    total_cost = 0.0

    log(f"  [AutoFix] Build broken — dispatching debugger agent", output)
    log(f"  [AutoFix] Language: {preflight_lang}, error preview: "
        f"{preflight_error[:200]}", output)

    # --- Phase 1: Debugger attempts ---
    for attempt in range(1, AUTOFIX_MAX_DEBUGGER_CYCLES + 1):
        log(f"  [AutoFix] Debugger attempt {attempt}/{AUTOFIX_MAX_DEBUGGER_CYCLES}", output)
        fix_task = {
            "id": task_id,
            "title": f"[AutoFix] Fix {preflight_lang} build errors",
            "description": (
                f"The project build is BROKEN. Your ONLY job is to make it compile clean.\n\n"
                f"**Build error output:**\n```\n{preflight_error}\n```\n\n"
                f"DO NOT work on any other task. DO NOT refactor. DO NOT add features.\n"
                f"Read the error, find the broken file(s), fix them, verify the build passes.\n"
                f"Start writing fixes IMMEDIATELY — do not read more than 3 files."
            ),
        }
        _, cost = await _dispatch_autofix_agent(
            "debugger", fix_task, project_dir, project_context,
            AUTOFIX_DEBUGGER_BUDGET, task_id, attempt, args, output)
        total_cost += cost

        if total_cost >= AUTOFIX_COST_LIMIT:
            log(f"  [AutoFix] Cost limit reached (${total_cost:.2f}). Giving up.", output)
            return False, total_cost, "cost_limit_exceeded"

        fixed, _, new_error = await preflight_build_check(project_dir, output=output)
        if fixed:
            log(f"  [AutoFix] Build FIXED by debugger (attempt {attempt}, cost: ${total_cost:.2f})", output)
            return True, total_cost, f"debugger_fixed_attempt_{attempt}"

        log(f"  [AutoFix] Debugger attempt {attempt} failed. Build still broken.", output)
        if new_error:
            preflight_error = new_error

    # --- Phase 2: Planner analysis ---
    log(f"  [AutoFix] Debugger failed {AUTOFIX_MAX_DEBUGGER_CYCLES}x. Escalating to planner.", output)
    planner_task = {
        "id": task_id,
        "title": f"[AutoFix] Analyze build failure and write fix plan",
        "description": (
            f"The project build is BROKEN and a debugger agent failed to fix it "
            f"after {AUTOFIX_MAX_DEBUGGER_CYCLES} attempts.\n\n"
            f"**Build error output:**\n```\n{preflight_error}\n```\n\n"
            f"Your job: 1) Analyze root cause 2) Identify EXACT files and lines "
            f"3) Write step-by-step fix plan with specific code changes 4) Output "
            f"as a numbered list. Do NOT fix the code — write the plan."
        ),
    }
    planner_result, cost = await _dispatch_autofix_agent(
        "planner", planner_task, project_dir, project_context,
        AUTOFIX_PLANNER_BUDGET, task_id, AUTOFIX_MAX_DEBUGGER_CYCLES + 1, args, output)
    total_cost += cost

    if total_cost >= AUTOFIX_COST_LIMIT:
        log(f"  [AutoFix] Cost limit reached after planner (${total_cost:.2f}). Giving up.", output)
        return False, total_cost, "cost_limit_exceeded"

    plan_text = str(planner_result.get("result") or planner_result.get("output", "No plan."))[:2000]

    # --- Phase 3: Guided debugger with plan ---
    log(f"  [AutoFix] Dispatching debugger with planner's fix plan", output)
    guided_task = {
        "id": task_id,
        "title": f"[AutoFix] Fix build using analysis plan",
        "description": (
            f"The project build is BROKEN. A planner produced this fix plan:\n\n"
            f"**Fix Plan:**\n{plan_text}\n\n"
            f"**Build error output:**\n```\n{preflight_error}\n```\n\n"
            f"Execute the plan. Fix the build. Verify it compiles. Start IMMEDIATELY."
        ),
    }
    _, cost = await _dispatch_autofix_agent(
        "debugger", guided_task, project_dir, project_context,
        AUTOFIX_DEBUGGER_BUDGET, task_id, AUTOFIX_MAX_DEBUGGER_CYCLES + 2, args, output)
    total_cost += cost

    fixed, _, _ = await preflight_build_check(project_dir, output=output)
    if fixed:
        log(f"  [AutoFix] Build FIXED by guided debugger (cost: ${total_cost:.2f})", output)
        return True, total_cost, "planner_guided_fix"

    log(f"  [AutoFix] Build still broken after all attempts (cost: ${total_cost:.2f}).", output)
    return False, total_cost, "all_attempts_failed"


# --- Loop Detection ---
# LOOP_WARNING_THRESHOLD, LOOP_TERMINATE_THRESHOLD, LoopDetector class,
# calculate_dynamic_budget, adjust_dynamic_budget extracted to equipa/monitoring.py

# --- Provider-Aware Agent Dispatch ---

async def dispatch_agent(cmd, role, output, max_turns, task_id, cycle,
                         system_prompt=None, project_dir=None, args=None):
    """Dispatch an agent using the configured provider (Claude or Ollama).

    For Claude: delegates to run_agent_streaming() or run_agent().
    For Ollama: delegates to run_ollama_agent().

    Returns the same result dict format regardless of provider.
    """
    # Security: verify skill file integrity before building any agent prompt
    if not verify_skill_integrity():
        return {
            "result": "blocked",
            "output": "CRITICAL: Skill integrity verification failed — agent dispatch refused. "
                      "Run --regenerate-manifest if changes are intentional.",
            "cost": 0,
            "duration": 0,
        }

    dispatch_config = getattr(args, "dispatch_config", None) if args else None
    provider_override = getattr(args, "provider", None) if args else None

    # Determine provider: CLI override > config > default (claude)
    if provider_override:
        provider = provider_override
    else:
        provider = get_provider(role, dispatch_config)

    if provider == "ollama" and system_prompt and project_dir:
        from ollama_agent import run_ollama_agent
        model = get_ollama_model(role, dispatch_config)
        base_url = get_ollama_base_url(dispatch_config)
        return run_ollama_agent(
            system_prompt=system_prompt,
            project_dir=project_dir,
            role=role,
            model=model,
            base_url=base_url,
            max_turns=max_turns,
        )

    # Default: Claude via run_agent_streaming
    use_streaming = role not in EARLY_TERM_EXEMPT_ROLES
    if use_streaming:
        return await run_agent_streaming(
            cmd, role=role, output=output, max_turns=max_turns,
            task_id=task_id, run_id=None, cycle_number=cycle,
            project_dir=project_dir)
    else:
        return await run_agent(cmd)


# --- Dev+Tester Loop (Phase 2) ---


# _apply_cost_totals extracted to equipa/roles.py

async def run_dev_test_loop(task, project_dir, project_context, args, output=None):
    """Run the Developer + Tester iteration loop.

    Flow per cycle:
    1. Check for checkpoint from a previous timed-out attempt
    2. Run Developer agent (with checkpoint + compaction/failure context)
    3. On timeout/max_turns -> save checkpoint for future resume
    4. Check if Developer marked task blocked -> exit
    5. Track FILES_CHANGED for progress detection
    6. Run Tester agent
    7. Parse Tester output:
       - pass -> clear checkpoints, exit success
       - no-tests -> clear checkpoints, exit accept
       - blocked -> exit
       - fail -> feed failures to next Developer cycle

    Returns (last_result, cycles_completed, outcome_reason) tuple.
    """
    # Auto-install deps before first cycle if needed
    await auto_install_dependencies(project_dir, output=output)

    # Pre-flight build check: detect build failures before agent starts
    task_description = task.get("description", "") if isinstance(task, dict) else ""
    preflight_ok, preflight_lang, preflight_error = await preflight_build_check(
        project_dir, task_description=task_description, output=output,
    )

    compaction_history = []  # accumulated context across cycles
    no_progress_count = 0    # consecutive cycles with no FILES_CHANGED
    continuation_count = 0   # auto-retries when developer runs out of turns
    total_cost = 0.0
    total_duration = 0.0
    task_id = task["id"]
    last_error_type = None   # track last error for lesson injection
    loop_detector = LoopDetector()  # detect repeated failing patterns

    # Load cost limits from dispatch config (overrides defaults in COST_LIMITS)
    dispatch_config = getattr(args, "dispatch_config", None) if args else None
    config_cost_limits = (dispatch_config or {}).get("cost_limits")

    # Reset status so orchestrator is authoritative
    conn = get_db_connection(write=True)
    conn.execute("UPDATE tasks SET status = 'in_progress' WHERE id = ?", (task_id,))
    conn.commit()
    conn.close()
    log(f"  [Setup] Task {task_id} status reset to in_progress (orchestrator manages lifecycle)", output)

    # Resolve model and turns using adaptive tiering
    complexity = get_task_complexity(task)
    # Use task-specified role if available, otherwise default to developer
    task_role = getattr(task, 'role', None) or (task.get('role') if isinstance(task, dict) else None) or "developer"
    dev_model = get_role_model(task_role, args, task=task)
    tester_model = get_role_model("tester", args, task=task)
    dev_turns_max = get_role_turns(task_role, args, task=task)
    tester_turns_max = get_role_turns("tester", args, task=task)

    # Dynamic turn budgets: start conservative, extend on progress
    dev_turns_allocated, _ = calculate_dynamic_budget(dev_turns_max)
    tester_turns_allocated, _ = calculate_dynamic_budget(tester_turns_max)

    # Resolve cost limit for this complexity tier
    effective_cost_limit = (config_cost_limits or COST_LIMITS).get(complexity, 10.0)
    log(f"  Task complexity: {complexity}", output)
    log(f"  Cost limit: ${effective_cost_limit:.2f} ({complexity})", output)
    log(f"  Developer: model={dev_model}, budget={dev_turns_allocated}/{dev_turns_max} "
        f"(dynamic, min={DYNAMIC_BUDGET_MIN_TURNS})", output)
    log(f"  Tester: model={tester_model}, budget={tester_turns_allocated}/{tester_turns_max} "
        f"(dynamic)", output)

    # Check for checkpoint from a previous timed-out attempt
    checkpoint_text, prev_attempt = load_checkpoint(task_id, role=task_role)
    if checkpoint_text:
        checkpoint_context = build_checkpoint_context(checkpoint_text, prev_attempt)
        compaction_history.append(checkpoint_context)
        log(f"  [Checkpoint] Loaded checkpoint from attempt #{prev_attempt} "
            f"({len(checkpoint_text)} chars). Agent will continue from there.", output)

    # Auto-fix: dispatch debugger agent to fix broken builds before main task
    if not preflight_ok and preflight_error:
        autofix_ok, autofix_cost, autofix_summary = await _handle_preflight_failure(
            task, project_dir, project_context,
            preflight_lang, preflight_error, args, output=output,
        )
        total_cost += autofix_cost

        if autofix_ok:
            # Build is fixed — proceed with the original task normally
            compaction_history.append(
                f"## Build Auto-Fixed\n\n"
                f"The build was broken but an auto-fix debugger agent repaired it "
                f"(method: {autofix_summary}, cost: ${autofix_cost:.2f}).\n"
                f"The build now passes. Proceed with your task normally."
            )
        else:
            # Build is still broken — mark task blocked
            log(f"  [AutoFix] Could not fix build. Marking task {task_id} as blocked "
                f"(reason: build_broken, autofix: {autofix_summary})", output)
            conn = get_db_connection(write=True)
            conn.execute(
                "UPDATE tasks SET status = 'blocked' WHERE id = ?", (task_id,)
            )
            conn.commit()
            conn.close()
            return {
                "early_terminated": True,
                "early_term_reason": f"build_broken ({autofix_summary})",
                "cost": total_cost,
                "duration": 0,
            }, 0, "build_broken"

    for cycle in range(1, MAX_DEV_TEST_CYCLES + 1):
        log(f"\n{'=' * 50}", output)
        log(f"  DEV-TEST CYCLE {cycle}/{MAX_DEV_TEST_CYCLES}", output)
        log(f"{'=' * 50}", output)

        # --- Developer Phase ---
        log(f"\n  [Cycle {cycle}] Running Developer agent "
            f"(budget: {dev_turns_allocated}/{dev_turns_max})...", output)

        # --- Inter-agent messages: inject unread messages into developer context ---
        agent_msgs = read_agent_messages(task_id, task_role)
        if agent_msgs:
            message_context = format_messages_for_prompt(agent_msgs)
            mark_messages_read(task_id, task_role, cycle)
            log(f"  [Cycle {cycle}] Injected {len(agent_msgs)} message(s) from other agents", output)
        else:
            message_context = ""

        # Build extra context from compaction history
        # Gated by anti_compaction_state feature flag — when disabled, agents
        # start each cycle fresh without prior cycle context
        _dc = getattr(args, "dispatch_config", None)
        if is_feature_enabled(_dc, "anti_compaction_state") and compaction_history:
            # After cycle 2+, consolidate ALL prior cycles into a single section
            # to prevent context rot from accumulated raw output
            if cycle >= 2 and len(compaction_history) > 1:
                consolidated = (
                    f"## Previous Attempts (Cycles 1-{cycle - 1})\n\n"
                    + "\n\n".join(compaction_history)
                )
                # Compact the consolidated section to prevent unbounded growth
                words = consolidated.split()
                if len(words) > 400:
                    consolidated = " ".join(words[:400]) + "\n[...earlier context trimmed...]"
                extra_context = consolidated
            else:
                extra_context = "\n\n".join(compaction_history)
        else:
            extra_context = ""

        # Prepend inter-agent messages if any
        if message_context:
            extra_context = message_context + "\n\n" + extra_context if extra_context else message_context

        dev_prompt = build_system_prompt(
            task, project_context, project_dir,
            role=task_role, extra_context=extra_context,
            dispatch_config=getattr(args, "dispatch_config", None),
            error_type=last_error_type,
            max_turns=dev_turns_allocated,
        )
        # Use streaming mode for early termination on non-exempt roles
        use_streaming = task_role not in EARLY_TERM_EXEMPT_ROLES
        dev_cmd = build_cli_command(
            dev_prompt, project_dir, dev_turns_allocated, dev_model, role=task_role,
            streaming=use_streaming,
        )

        dev_result = await dispatch_agent(
            dev_cmd, role=task_role, output=output, max_turns=dev_turns_allocated,
            task_id=task_id, cycle=cycle, system_prompt=dev_prompt,
            project_dir=project_dir, args=args)
        # Tag result with dynamic budget info for telemetry
        dev_result["turns_allocated"] = dev_turns_allocated
        dev_result["turns_max"] = dev_turns_max
        total_duration += dev_result.get("duration", 0)
        total_cost += _accumulate_cost(
            dev_result, f"[Cycle {cycle}] Developer", output)

        # Cost-based circuit breaker
        cost_reason = _check_cost_limit(total_cost, complexity, config_cost_limits)
        if cost_reason:
            log(f"  [Cycle {cycle}] {cost_reason}", output)
            loop_detector.record(dev_result, cycle)
            _apply_cost_totals(dev_result, total_cost, total_duration)
            dev_result["early_terminated"] = True
            dev_result["early_term_reason"] = cost_reason
            return dev_result, cycle, "cost_limit_exceeded"

        # Check for early termination
        if dev_result.get("early_terminated"):
            reason = dev_result.get("early_term_reason", "unknown")
            log(f"  [Cycle {cycle}] Developer early-terminated: {reason}", output)
            # Cohesion: record early termination so loop detector sees it for cross-cycle learning
            loop_detector.record(dev_result, cycle)
            return dev_result, cycle, "early_terminated"

        # Check for agent-initiated early completion (agent chose to stop)
        if dev_result.get("early_completed"):
            ec_reason = dev_result.get("early_complete_reason", "")
            log(f"  [Cycle {cycle}] Developer signaled early completion: "
                f"{ec_reason}", output)
            # Skip tester if agent says no changes were needed
            no_changes_phrases = [
                "no changes needed", "no changes required",
                "no modifications needed", "nothing to change",
                "already implemented", "already exists",
                "no work needed", "task already complete",
            ]
            if any(phrase in ec_reason.lower() for phrase in no_changes_phrases):
                log(f"  [Cycle {cycle}] Skipping tester — agent reported no "
                    f"changes needed.", output)
                clear_checkpoints(task_id)
                dev_result["cost"] = total_cost
                dev_result["duration"] = total_duration
                return dev_result, cycle, "early_completed_no_changes"
            # Otherwise, agent completed with changes — run tester as normal
            log(f"  [Cycle {cycle}] Agent completed early with changes — "
                f"proceeding to tester.", output)

        # Check for timeout or max_turns — save checkpoint for resume
        is_timeout = any("timed out" in e for e in dev_result.get("errors", []))
        is_max_turns = any("max turns" in e for e in dev_result.get("errors", []))

        if is_timeout or is_max_turns:
            reason = "timed out" if is_timeout else "hit max turns"
            # Track error type for lesson injection on next iteration
            last_error_type = "timeout" if is_timeout else "max_turns"
            continuation_count += 1
            log(f"  [Cycle {cycle}] Developer {reason}. "
                f"(continuation {continuation_count}/{MAX_CONTINUATIONS})", output)

            # Save checkpoint
            result_text = dev_result.get("result_text", "")
            if result_text:
                attempt_num = prev_attempt + cycle
                cp_path = save_checkpoint(task_id, attempt_num, result_text, role=task_role)
                if cp_path:
                    log(f"  [Checkpoint] Saved ({len(result_text)} chars) -> {cp_path.name}", output)

            # Auto-continue: spawn fresh agent with checkpoint context
            if continuation_count < MAX_CONTINUATIONS:
                log(f"  [Auto-Continue] Spawning new developer agent to continue...", output)
                if result_text:
                    checkpoint_context = build_checkpoint_context(
                        result_text, prev_attempt + cycle)
                    compaction_history.append(checkpoint_context)
                continue  # skip tester, go to next dev-test cycle

            # All continuations exhausted
            log(f"  [Auto-Continue] All {MAX_CONTINUATIONS} continuations exhausted. "
                f"Marking blocked.", output)
            outcome = "developer_timeout" if is_timeout else "developer_max_turns"
            return dev_result, cycle, outcome

        # Check for agent failure
        if not dev_result["success"]:
            # If agent made file changes despite "failure", give it credit
            # and proceed to tester (the work exists on disk even if stream broke)
            if dev_result.get("has_file_changes"):
                log(f"  [Cycle {cycle}] Developer agent reported failure but made file changes. "
                    f"Proceeding to tester.", output)
                dev_result["success"] = True  # Override — work exists on disk
            else:
                log(f"  [Cycle {cycle}] Developer agent failed.", output)
                return dev_result, cycle, "developer_failed"

        # Compaction: ALWAYS compact developer output before passing to next cycle
        # (context engineering: never pass raw agent output between cycles)
        dev_turns_used_for_compact = dev_result.get("num_turns", 0)
        log(f"  [Cycle {cycle}] Compacting developer output "
            f"({dev_turns_used_for_compact} turns)...", output)
        summary = build_compaction_summary("Developer", dev_result, cycle, task)
        compaction_history.append(summary)

        # Check if Developer marked task blocked
        status = _get_task_status(task["id"])
        if status == "blocked":
            log(f"  [Cycle {cycle}] Developer marked task as BLOCKED.", output)
            return dev_result, cycle, "developer_blocked"

        # Progress detection: check FILES_CHANGED marker + turn-based heuristic
        files_changed = parse_developer_output(dev_result.get("result_text", ""))
        dev_turns_used = dev_result.get("num_turns", 0)

        # Consider it progress if: FILES_CHANGED has items, OR dev used 3+ turns
        # (agents often do work but forget to output the marker)
        made_progress = bool(files_changed) or dev_turns_used >= 3

        if made_progress:
            # Clear error type on successful progress
            last_error_type = None

        if not made_progress:
            no_progress_count += 1
            log(f"  [Cycle {cycle}] No progress detected ({dev_turns_used} turns, no files marker) "
                f"({no_progress_count}/{NO_PROGRESS_LIMIT} consecutive).", output)
            if no_progress_count >= NO_PROGRESS_LIMIT:
                log(f"  [Cycle {cycle}] No progress for {NO_PROGRESS_LIMIT} cycles. "
                    f"Marking blocked.", output)
                return dev_result, cycle, "no_progress"
        else:
            no_progress_count = 0
            if files_changed:
                log(f"  [Cycle {cycle}] Developer changed {len(files_changed)} file(s): "
                    f"{', '.join(files_changed[:5])}", output)
            else:
                log(f"  [Cycle {cycle}] Developer used {dev_turns_used} turns "
                    f"(no FILES_CHANGED marker, but counting as progress).", output)

        # --- Dynamic Budget Adjustment ---
        prev_budget = dev_turns_allocated
        dev_turns_allocated = adjust_dynamic_budget(
            dev_turns_allocated, dev_turns_max,
            dev_result.get("result_text", ""))
        if dev_turns_allocated != prev_budget:
            log(f"  [DynBudget] Developer budget adjusted: {prev_budget} -> "
                f"{dev_turns_allocated}/{dev_turns_max}", output)

        # --- Loop Detection ---
        loop_action = loop_detector.record(dev_result, cycle)
        if loop_action == "terminate":
            log(f"  [Cycle {cycle}] LOOP DETECTED: Agent repeated the same failing "
                f"pattern {loop_detector.consecutive_same} times. Terminating early.", output)
            # Attach loop info to the result for telemetry
            dev_result.setdefault("errors", []).append(loop_detector.termination_summary())
            return dev_result, cycle, "loop_detected"
        elif loop_action == "warn":
            log(f"  [Cycle {cycle}] Loop warning: Agent has repeated the same pattern "
                f"{loop_detector.consecutive_same} times. Injecting 'try different approach' "
                f"guidance.", output)
            compaction_history.append(loop_detector.warning_message())
            # Log the warning in error_summary for telemetry
            dev_result.setdefault("errors", []).append(
                f"Loop warning: agent repeated same pattern "
                f"{loop_detector.consecutive_same} times (cycle {cycle})"
            )

        # --- Tester Phase ---
        log(f"\n  [Cycle {cycle}] Running Tester agent "
            f"(budget: {tester_turns_allocated}/{tester_turns_max})...", output)

        tester_prompt = build_system_prompt(
            task, project_context, project_dir, role="tester",
            dispatch_config=getattr(args, "dispatch_config", None),
            max_turns=tester_turns_allocated,
        )
        tester_cmd = build_cli_command(
            tester_prompt, project_dir, tester_turns_allocated, tester_model, role="tester",
            streaming=True,
        )

        tester_result = await dispatch_agent(
            tester_cmd, role="tester", output=output, max_turns=tester_turns_allocated,
            task_id=task_id, cycle=cycle, system_prompt=tester_prompt,
            project_dir=project_dir, args=args)
        # Tag tester result with dynamic budget info for telemetry
        tester_result["turns_allocated"] = tester_turns_allocated
        tester_result["turns_max"] = tester_turns_max
        total_duration += tester_result.get("duration", 0)
        total_cost += _accumulate_cost(
            tester_result, f"[Cycle {cycle}] Tester", output)

        # Cost-based circuit breaker after tester phase
        cost_reason = _check_cost_limit(total_cost, complexity, config_cost_limits)
        if cost_reason:
            log(f"  [Cycle {cycle}] {cost_reason} (after tester)", output)
            _apply_cost_totals(tester_result, total_cost, total_duration)
            tester_result["early_terminated"] = True
            tester_result["early_term_reason"] = cost_reason
            return tester_result, cycle, "cost_limit_exceeded"

        # Check for early termination (stuck tester)
        # Tester early-termination = treat as no-tests, accept developer work
        if tester_result.get("early_terminated"):
            reason = tester_result.get("early_term_reason", "unknown")
            log(f"  [Cycle {cycle}] Tester early-terminated: {reason}", output)
            log(f"  [Cycle {cycle}] Treating tester early-termination as no-tests (accepting dev work)", output)
            tester_result["result"] = "no-tests"
            tester_result["tests_run"] = 0
            tester_result["tests_passed"] = 0

        # Check for timeout
        if any("timed out" in e for e in tester_result.get("errors", [])):
            log(f"  [Cycle {cycle}] Tester timed out.", output)
            return tester_result, cycle, "tester_timeout"

        # Compaction: ALWAYS compact tester output before passing to next cycle
        # (context engineering: never pass raw agent output between cycles)
        tester_turns_for_compact = tester_result.get("num_turns", 0)
        log(f"  [Cycle {cycle}] Compacting tester output "
            f"({tester_turns_for_compact} turns)...", output)
        summary = build_compaction_summary("Tester", tester_result, cycle, task)
        compaction_history.append(summary)

        # Parse Tester output
        test_results = parse_tester_output(tester_result.get("result_text", ""))
        test_outcome = test_results["result"]

        log(f"  [Cycle {cycle}] Tester result: {test_outcome} "
            f"({test_results['tests_passed']}/{test_results['tests_run']} passed)", output)

        if test_outcome == "pass":
            log(f"  [Cycle {cycle}] All tests passed!", output)
            msg_content = json.dumps({
                "outcome": "pass",
                "tests_passed": test_results["tests_passed"],
                "tests_run": test_results["tests_run"],
            })
            post_agent_message(task_id, cycle, "tester", task_role,
                               "test_passed", msg_content)
            log(f"  [Cycle {cycle}] Posted test_passed message for {task_role}", output)
            clear_checkpoints(task_id)  # success — no need for checkpoints
            _apply_cost_totals(tester_result, total_cost, total_duration)
            return tester_result, cycle, "tests_passed"

        elif test_outcome == "no-tests":
            log(f"  [Cycle {cycle}] No tests found. Accepting Developer result.", output)
            clear_checkpoints(task_id)  # success — no need for checkpoints
            _apply_cost_totals(dev_result, total_cost, total_duration)
            return dev_result, cycle, "no_tests"

        elif test_outcome == "blocked":
            log(f"  [Cycle {cycle}] Tester is blocked (missing dependency, build error, etc.).", output)
            msg_content = json.dumps({
                "outcome": "blocked",
                "details": test_results.get("failure_details", [])[:3],
            })
            post_agent_message(task_id, cycle, "tester", task_role,
                               "blocker_update", msg_content)
            log(f"  [Cycle {cycle}] Posted blocker_update message for {task_role}", output)
            return tester_result, cycle, "tester_blocked"

        elif (test_outcome == "unknown" and test_results["tests_run"] == 0
              and test_results["tests_failed"] == 0):
            # Tester couldn't produce structured output and no tests actually ran
            log(f"  [Cycle {cycle}] Tester returned unknown with 0 tests. "
                f"Treating as no-tests.", output)
            clear_checkpoints(task_id)
            _apply_cost_totals(dev_result, total_cost, total_duration)
            return dev_result, cycle, "no_tests"

        else:
            # test_outcome == "fail" (with actual test failures)
            log(f"  [Cycle {cycle}] {test_results['tests_failed']} test(s) failed.", output)
            msg_content = json.dumps({
                "outcome": "fail",
                "tests_failed": test_results["tests_failed"],
                "tests_run": test_results["tests_run"],
                "failures": test_results.get("failure_details", [])[:5],
            })
            post_agent_message(task_id, cycle, "tester", task_role,
                               "test_failures", msg_content)
            log(f"  [Cycle {cycle}] Posted test_failures message for {task_role}", output)
            if test_results["failure_details"]:
                for detail in test_results["failure_details"][:5]:
                    safe_detail = detail.encode("ascii", errors="replace").decode("ascii")
                    log(f"    - {safe_detail}", output)

            # Feed failures to next Developer cycle
            failure_context = build_test_failure_context(test_results, cycle)
            compaction_history.append(failure_context)

    # All cycles exhausted
    log(f"\n  All {MAX_DEV_TEST_CYCLES} dev-test cycles exhausted. Marking blocked.", output)
    # Return the last tester result with accumulated totals
    tester_result["cost"] = total_cost
    tester_result["duration"] = total_duration
    return tester_result, MAX_DEV_TEST_CYCLES, "cycles_exhausted"


# --- Security Review (automatic post dev-test) ---


async def run_security_review(task, project_dir, project_context, args, output=None):
    """Run an automatic security review after dev-test succeeds.

    Uses the security-reviewer role with ClaudeStick tools.
    Only runs if security_review is enabled in dispatch config.
    """
    log(f"\n{'=' * 50}", output)
    log(f"  SECURITY REVIEW", output)
    log(f"{'=' * 50}", output)
    log(f"\n  Running security reviewer agent...", output)

    # Build security review prompt with explicit instructions to use all tools
    security_task = dict(task)  # copy
    security_task["description"] = (
        f"Security review of code written for: {task['title']}. "
        f"Review ALL files changed in the project directory. "
        f"YOU MUST use ALL ClaudeStick security tools: static-analysis, "
        f"audit-context-building, variant-analysis, differential-review, "
        f"fix-review, semgrep-rule-creator, and sharp-edges. "
        f"Check for OWASP Top 10 vulnerabilities, zero-day risks in dependencies, "
        f"and any security anti-patterns. "
        f"Write findings to a SECURITY-REVIEW.md file in the project directory. "
        f"Rate each finding: CRITICAL, HIGH, MEDIUM, LOW, INFO. "
        f"Original task description: {task['description']}"
    )

    sec_turns = get_role_turns("security-reviewer", args, task=task)
    sec_prompt = build_system_prompt(
        security_task, project_context, project_dir,
        role="security-reviewer",
        dispatch_config=getattr(args, "dispatch_config", None),
        max_turns=sec_turns,
    )
    sec_model = get_role_model("security-reviewer", args, task=task)
    sec_cmd = build_cli_command(
        sec_prompt, project_dir, sec_turns, sec_model, role="security-reviewer",
    )

    # Use security_review_timeout from dispatch config (default 15 min)
    dc = load_dispatch_config(None)
    sec_timeout = dc.get("security_review_timeout", 900)
    sec_result = await run_agent(sec_cmd, timeout=sec_timeout)

    if sec_result["success"]:
        log(f"  Security review completed in {sec_result.get('duration', 0):.1f}s", output)
        # Parse for critical findings
        result_text = sec_result.get("result_text", "")
        critical_count = result_text.lower().count("critical")
        high_count = result_text.lower().count("high")
        if critical_count > 0 or high_count > 0:
            log(f"  WARNING: Found {critical_count} CRITICAL and {high_count} HIGH severity findings", output)
        else:
            log(f"  No critical or high severity findings", output)

        # Feed security findings back into developer lessons
        project_id = task.get("project_id")
        findings = _extract_security_findings(result_text)
        if findings:
            count = _create_security_lessons(findings, project_id)
            if count > 0:
                log(f"  Created {count} developer lesson(s) from security findings", output)
    else:
        log(f"  Security review agent failed.", output)
        for err in sec_result.get("errors", []):
            log(f"    Error: {err[:200]}", output)

    return sec_result


def _extract_security_findings(result_text):
    """Extract individual CRITICAL and HIGH severity findings from security review output.

    Looks for lines containing severity markers and extracts the finding description.
    Returns a list of (severity, description) tuples.
    """
    findings = []
    if not result_text:
        return findings

    lines = result_text.split("\n")
    for i, line in enumerate(lines):
        line_stripped = line.strip()
        line_upper = line_stripped.upper()

        # Match lines that contain severity ratings like "CRITICAL:", "HIGH:",
        # "**CRITICAL**", "- CRITICAL:", "[CRITICAL]", etc.
        severity = None
        if "CRITICAL" in line_upper and any(
            p in line_upper for p in ("CRITICAL:", "CRITICAL**", "[CRITICAL]", "CRITICAL —", "CRITICAL -")
        ):
            severity = "CRITICAL"
        elif "HIGH" in line_upper and any(
            p in line_upper for p in ("HIGH:", "HIGH**", "[HIGH]", "HIGH —", "HIGH -")
        ):
            severity = "HIGH"

        if severity:
            # Extract the finding text — everything after the severity marker
            desc = line_stripped
            # Strip common prefixes: bullets, markdown bold, brackets
            for prefix in ("- ", "* ", "• "):
                if desc.startswith(prefix):
                    desc = desc[len(prefix):]

            # If the line is very short, grab the next line too for context
            if len(desc) < 40 and i + 1 < len(lines) and lines[i + 1].strip():
                desc = desc + " " + lines[i + 1].strip()

            # Cap length for lesson storage
            if len(desc) > 500:
                desc = desc[:497] + "..."

            findings.append((severity, desc))

    return findings


def _create_security_lessons(findings, project_id=None):
    """Insert security findings as developer lessons so they get injected into future dev prompts.

    Lessons are created with role='developer' and source='security-reviewer' so the existing
    get_relevant_lessons(role='developer') pipeline picks them up automatically.
    Deduplicates by error_signature to avoid flooding the lessons table.

    Sanitizes finding descriptions before storage (PM-33) since they originate
    from agent output which could contain prompt-injection payloads.
    """
    conn = get_db_connection(write=True)
    created = 0

    for severity, description in findings:
        # Sanitize the agent-produced description before storing (PM-33)
        safe_description = sanitize_lesson_content(description)
        if not safe_description:
            continue

        # Build a signature for dedup — normalize to lowercase, strip punctuation
        sig = re.sub(r'[^\w\s]', '', safe_description.lower())[:200]

        # Check if a similar lesson already exists
        existing = conn.execute(
            """SELECT id FROM lessons_learned
               WHERE error_signature = ? AND source = 'security-reviewer' AND active = 1""",
            (sig,),
        ).fetchone()

        if existing:
            # Bump times_seen instead of creating a duplicate
            conn.execute(
                """UPDATE lessons_learned
                   SET times_seen = times_seen + 1, updated_at = datetime('now')
                   WHERE id = ?""",
                (existing["id"],),
            )
        else:
            # Create a developer-facing lesson from the security finding
            lesson_text = (
                f"Security review found {severity} issue: {safe_description}. "
                f"Check for this pattern in future code and prevent it proactively."
            )
            # Validate structure before inserting
            if not validate_lesson_structure(lesson_text):
                continue
            lesson_text = sanitize_lesson_content(lesson_text)
            conn.execute(
                """INSERT INTO lessons_learned
                   (project_id, role, error_type, error_signature, lesson, source, times_seen)
                   VALUES (?, 'developer', 'security', ?, ?, 'security-reviewer', 1)""",
                (project_id, sig, lesson_text),
            )
            created += 1

    conn.commit()
    conn.close()
    return created


# --- Manager Mode: Planner & Evaluator (Phase 3) ---

def build_planner_prompt(goal, project_id, project_dir, project_context):
    """Build the system prompt for the Planner agent.

    The Planner gets the goal, project context, and codebase access.
    It does NOT get a task — it creates tasks.
    """
    common_path = PROMPTS_DIR / "_common.md"
    role_path = ROLE_PROMPTS["planner"]

    common_text = common_path.read_text(encoding="utf-8")
    role_text = role_path.read_text(encoding="utf-8")
    template = common_text + "\n\n---\n\n" + role_text

    # Replace project_id placeholder (planner doesn't have a task_id)
    prompt = template.replace("{project_id}", str(project_id))
    prompt = prompt.replace("{task_id}", "N/A")

    # Per-prompt unpredictable delimiter for untrusted content isolation
    _delim = _make_untrusted_delimiter()

    # Helper: wrap content in both task-input tags AND unpredictable delimiter
    def _wrap(tag_type, content):
        inner = wrap_untrusted(content, _delim)
        return f'<task-input type="{tag_type}" trust="user">\n{inner}\n</task-input>'

    # Append goal and project context
    lines = [
        "## Goal",
        "",
        _wrap("goal", goal),
        "",
        f"## Project Info",
        f"- **Project ID:** {project_id}",
        f"- **Working Directory:** {project_dir}",
        "",
    ]

    # Add project context
    session = project_context.get("last_session")
    if session:
        ctx_parts = [f"Last session ({session.get('session_date', 'unknown')}):"]
        ctx_parts.append(session.get("summary", "No summary"))
        if session.get("next_steps"):
            ctx_parts.append(f"Next steps: {session['next_steps']}")
        lines.append("## Recent Project Context")
        lines.append(_wrap("session-context", "\n".join(ctx_parts)))
        lines.append("")

    questions = project_context.get("open_questions", [])
    if questions:
        q_lines = [f"- {q['question']}" for q in questions]
        lines.append("## Open Questions (unresolved)")
        lines.append(_wrap("open-questions", "\n".join(q_lines)))
        lines.append("")

    prompt = prompt + "\n\n---\n\n" + "\n".join(lines)
    return prompt


def build_evaluator_prompt(goal, project_id, project_dir, project_context,
                           completed_tasks, blocked_tasks):
    """Build the system prompt for the Evaluator agent.

    The Evaluator gets the original goal, completed/blocked task info,
    and codebase access to verify work.
    """
    common_path = PROMPTS_DIR / "_common.md"
    role_path = ROLE_PROMPTS["evaluator"]

    common_text = common_path.read_text(encoding="utf-8")
    role_text = role_path.read_text(encoding="utf-8")
    template = common_text + "\n\n---\n\n" + role_text

    prompt = template.replace("{project_id}", str(project_id))
    prompt = prompt.replace("{task_id}", "N/A")

    # Per-prompt unpredictable delimiter for untrusted content isolation
    _delim = _make_untrusted_delimiter()

    def _wrap(tag_type, content, trust="user"):
        inner = wrap_untrusted(content, _delim)
        return f'<task-input type="{tag_type}" trust="{trust}">\n{inner}\n</task-input>'

    lines = [
        "## Original Goal",
        "",
        _wrap("goal", goal),
        "",
        f"## Project Info",
        f"- **Project ID:** {project_id}",
        f"- **Working Directory:** {project_dir}",
        "",
    ]

    # Show completed tasks — task titles/descriptions come from DB
    if completed_tasks:
        ct_lines = []
        for t in completed_tasks:
            ct_lines.append(f"- **#{t['id']}** {t['title']} — {t.get('description', 'No description')[:200]}")
        lines.append("## Completed Tasks")
        lines.append(_wrap("completed-tasks", "\n".join(ct_lines), trust="database"))
        lines.append("")

    # Show blocked tasks — task titles/descriptions come from DB
    if blocked_tasks:
        bt_lines = []
        for t in blocked_tasks:
            bt_lines.append(f"- **#{t['id']}** {t['title']} — {t.get('description', 'No description')[:200]}")
        lines.append("## Blocked Tasks")
        lines.append(_wrap("blocked-tasks", "\n".join(bt_lines), trust="database"))
        lines.append("")

    if not completed_tasks and not blocked_tasks:
        lines.append("## Task Results")
        lines.append("No tasks were completed or blocked. This is unexpected.")
        lines.append("")

    prompt = prompt + "\n\n---\n\n" + "\n".join(lines)
    return prompt


def parse_planner_output(result_text):
    """Extract TASKS_CREATED list from Planner agent output.

    Returns a list of integer task IDs, or empty list on failure.
    """
    if not result_text:
        return []

    for line in result_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("TASKS_CREATED:"):
            value = stripped.split(":", 1)[1].strip()
            if not value or value.lower() == "none":
                return []
            # Parse comma-separated IDs
            ids = []
            for part in value.split(","):
                part = part.strip()
                try:
                    ids.append(int(part))
                except ValueError:
                    continue
            return ids

    return []


def parse_evaluator_output(result_text):
    """Extract GOAL_STATUS, TASKS_CREATED, EVALUATION, BLOCKERS from Evaluator output.

    Returns a dict with parsed fields.
    """
    parsed = {
        "goal_status": "blocked",  # default to blocked if parsing fails
        "tasks_created": [],
        "evaluation": "",
        "blockers": "none",
    }

    if not result_text:
        return parsed

    for line in result_text.splitlines():
        stripped = line.strip()

        if stripped.startswith("GOAL_STATUS:"):
            status = stripped.split(":", 1)[1].strip().lower()
            if status in ("complete", "needs_more", "blocked"):
                parsed["goal_status"] = status

        elif stripped.startswith("TASKS_CREATED:"):
            value = stripped.split(":", 1)[1].strip()
            if value and value.lower() != "none":
                for part in value.split(","):
                    part = part.strip()
                    try:
                        parsed["tasks_created"].append(int(part))
                    except ValueError:
                        continue

        elif stripped.startswith("EVALUATION:"):
            parsed["evaluation"] = stripped.split(":", 1)[1].strip()

        elif stripped.startswith("BLOCKERS:"):
            parsed["blockers"] = stripped.split(":", 1)[1].strip()

    return parsed


async def run_planner_agent(goal, project_id, project_dir, project_context, args,
                            output=None):
    """Spawn the Planner agent to break a goal into tasks.

    Returns (result, task_ids) tuple.
    """
    log("\n  [Planner] Building prompt...", output)
    system_prompt = build_planner_prompt(goal, project_id, project_dir, project_context)

    cmd = [
        "claude",
        "-p",
        f"Break this goal into tasks. Project dir: {project_dir}",
        "--output-format", "json",
        "--model", args.model,
        "--max-turns", str(get_role_turns("planner", args)),
        "--no-session-persistence",
        "--append-system-prompt", system_prompt,
        "--mcp-config", str(MCP_CONFIG),
        "--add-dir", str(project_dir),
        "--permission-mode", "bypassPermissions",
    ]

    log(f"  [Planner] Spawning agent (prompt: {len(system_prompt)} chars)...", output)
    result = await run_agent(cmd)

    if not result["success"]:
        log(f"  [Planner] Agent failed: {result.get('errors', [])}", output)
        return result, []

    task_ids = parse_planner_output(result.get("result_text", ""))

    # Validate task count
    if len(task_ids) > MAX_TASKS_PER_PLAN:
        log(f"  [Planner] Created {len(task_ids)} tasks (max {MAX_TASKS_PER_PLAN}). "
            f"Using first {MAX_TASKS_PER_PLAN}.", output)
        task_ids = task_ids[:MAX_TASKS_PER_PLAN]

    if task_ids:
        log(f"  [Planner] Created {len(task_ids)} tasks: {task_ids}", output)
    else:
        log(f"  [Planner] No task IDs found in output.", output)

    return result, task_ids


async def run_evaluator_agent(goal, project_id, project_dir, project_context,
                               completed_tasks, blocked_tasks, args, output=None):
    """Spawn the Evaluator agent to assess goal completion.

    Returns (result, parsed_eval) tuple.
    """
    log("\n  [Evaluator] Building prompt...", output)
    system_prompt = build_evaluator_prompt(
        goal, project_id, project_dir, project_context,
        completed_tasks, blocked_tasks,
    )

    cmd = [
        "claude",
        "-p",
        f"Evaluate whether this goal is complete. Project dir: {project_dir}",
        "--output-format", "json",
        "--model", args.model,
        "--max-turns", str(get_role_turns("evaluator", args)),
        "--no-session-persistence",
        "--append-system-prompt", system_prompt,
        "--mcp-config", str(MCP_CONFIG),
        "--add-dir", str(project_dir),
        "--permission-mode", "bypassPermissions",
    ]

    log(f"  [Evaluator] Spawning agent (prompt: {len(system_prompt)} chars)...", output)
    result = await run_agent(cmd)

    if not result["success"]:
        log(f"  [Evaluator] Agent failed: {result.get('errors', [])}", output)
        return result, {"goal_status": "blocked", "tasks_created": [],
                        "evaluation": "Evaluator agent failed", "blockers": "Agent error"}

    parsed = parse_evaluator_output(result.get("result_text", ""))

    # Validate follow-up task count
    if len(parsed["tasks_created"]) > MAX_FOLLOWUP_TASKS:
        log(f"  [Evaluator] Created {len(parsed['tasks_created'])} follow-up tasks "
            f"(max {MAX_FOLLOWUP_TASKS}). Using first {MAX_FOLLOWUP_TASKS}.", output)
        parsed["tasks_created"] = parsed["tasks_created"][:MAX_FOLLOWUP_TASKS]

    log(f"  [Evaluator] Goal status: {parsed['goal_status']}", output)
    log(f"  [Evaluator] Evaluation: {parsed['evaluation'][:200]}", output)
    if parsed["tasks_created"]:
        log(f"  [Evaluator] Follow-up tasks: {parsed['tasks_created']}", output)

    return result, parsed


async def run_manager_loop(goal, project_id, project_dir, project_context, args,
                            output=None):
    """Run the full Manager loop: Plan -> Execute -> Evaluate -> Repeat.

    Returns (outcome, total_rounds, all_completed, all_blocked, total_cost, total_duration).
    """
    max_rounds = args.max_rounds
    all_completed = []
    all_blocked = []
    total_cost = 0.0
    total_duration = 0.0

    for round_num in range(1, max_rounds + 1):
        log(f"\n{'#' * 60}", output)
        log(f"  MANAGER ROUND {round_num}/{max_rounds}", output)
        log(f"{'#' * 60}", output)

        # --- Phase 1: Plan ---
        log(f"\n--- Phase 1: Planning ---", output)
        planner_result, task_ids = await run_planner_agent(
            goal, project_id, project_dir, project_context, args, output=output,
        )
        total_duration += planner_result.get("duration", 0)
        if planner_result.get("cost"):
            total_cost += planner_result["cost"]

        if not task_ids:
            log(f"\n  [Manager] Planner failed to create tasks. Aborting.", output)
            return "planner_failed", round_num, all_completed, all_blocked, total_cost, total_duration

        # Fetch the created tasks
        tasks = fetch_tasks_by_ids(task_ids)
        if not tasks:
            log(f"\n  [Manager] Could not fetch tasks {task_ids} from TheForge. Aborting.", output)
            return "planner_failed", round_num, all_completed, all_blocked, total_cost, total_duration

        # --- Phase 2: Execute each task via Dev+Tester loop ---
        log(f"\n--- Phase 2: Executing {len(tasks)} tasks ---", output)
        round_completed = []
        round_blocked = []

        for i, task in enumerate(tasks, 1):
            log(f"\n{'=' * 50}", output)
            log(f"  TASK {i}/{len(tasks)}: #{task['id']} - {task['title']}", output)
            log(f"{'=' * 50}", output)

            # Re-fetch task status (planner may have set it to todo)
            current_status = _get_task_status(task["id"])
            if current_status == "done":
                log(f"  Task already marked done. Skipping.", output)
                round_completed.append(task)
                continue

            result, cycles, outcome = await run_dev_test_loop(
                task, project_dir, project_context, args, output=output,
            )
            total_duration += result.get("duration", 0)
            if result.get("cost"):
                total_cost += result["cost"]

            # Orchestrator-side DB update (don't rely on agent)
            update_task_status(task["id"], outcome, output=output)

            if outcome in ("tests_passed", "no_tests"):
                round_completed.append(task)
                log(f"  Task #{task['id']}: COMPLETED ({outcome})", output)
            else:
                round_blocked.append(task)
                log(f"  Task #{task['id']}: BLOCKED ({outcome})", output)

        all_completed.extend(round_completed)
        all_blocked.extend(round_blocked)

        # --- Phase 3: Evaluate ---
        log(f"\n--- Phase 3: Evaluating ---", output)
        log(f"  Completed: {len(round_completed)}, Blocked: {len(round_blocked)}", output)

        eval_result, eval_parsed = await run_evaluator_agent(
            goal, project_id, project_dir, project_context,
            all_completed, all_blocked, args, output=output,
        )
        total_duration += eval_result.get("duration", 0)
        if eval_result.get("cost"):
            total_cost += eval_result["cost"]

        if eval_parsed["goal_status"] == "complete":
            log(f"\n  [Manager] Goal COMPLETE!", output)
            return "goal_complete", round_num, all_completed, all_blocked, total_cost, total_duration

        elif eval_parsed["goal_status"] == "blocked":
            log(f"\n  [Manager] Goal BLOCKED: {eval_parsed['blockers']}", output)
            return "goal_blocked", round_num, all_completed, all_blocked, total_cost, total_duration

        elif eval_parsed["goal_status"] == "needs_more":
            if round_num >= max_rounds:
                log(f"\n  [Manager] Needs more work but max rounds reached.", output)
                break
            log(f"\n  [Manager] Needs more work. Continuing to round {round_num + 1}...", output)
            if eval_parsed["tasks_created"]:
                continue

    return "rounds_exhausted", max_rounds, all_completed, all_blocked, total_cost, total_duration


# print_manager_summary extracted to equipa/output.py


# --- Verification ---

# verify_task_updated extracted to equipa/tasks.py


# _print_task_summary, print_summary, print_dev_test_summary extracted to equipa/output.py

# _is_git_repo extracted to equipa/git_ops.py


# resolve_project_dir extracted to equipa/tasks.py


# --- Parallel Goals (Phase 4A) ---

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

