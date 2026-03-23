# Anti-Compaction State Persistence — Task #1586

## Summary

Added `.forge-state.json` anti-compaction state persistence to EQUIPA agent prompts. This teaches agents to maintain a checkpoint file on disk that survives Claude Code context compaction events.

## What Changed

### 1. `prompts/_common.md` — New "State Persistence (Anti-Compaction)" section

Added instructions for all agents to:
- Maintain a `.forge-state.json` file in the project root
- Update it after every significant action (file edit, test run, decision)
- Read it first on startup to recover from context compaction
- Delete it when the task is complete
- Never commit it to git

The JSON schema includes: `task_id`, `current_step`, `files_read`, `files_changed`, `decisions`, `tests_run`, `next_action`.

### 2. `.gitignore` — Added `.forge-state.json`

Prevents the ephemeral state file from being accidentally committed.

### 3. `forge_orchestrator.py` — Worktree cleanup

Added cleanup of `.forge-state.json` in the worktree teardown section (line ~6583). When worktrees are removed after task completion, any leftover state files are deleted first.

## How It Works

1. Agent starts a task → creates `.forge-state.json` with initial state
2. Agent edits files, runs tests → updates `.forge-state.json` after each action
3. Claude Code compacts context mid-task → agent loses in-memory context
4. Agent resumes → reads `.forge-state.json` → knows what files were changed, what tests ran, and what to do next
5. Agent completes task → deletes `.forge-state.json`

## Impact

- **Zero code changes** — purely a prompt-level feature
- **Backwards compatible** — agents without the update simply won't create the file
- **Immediate value** — addresses the #1 cause of agent failure after compaction (re-reading files, re-planning, wasting turns)
