# /forge-start

Session start protocol for TheForge. Run this at the beginning of every session.

## What This Skill Does

1. Runs the ForgeMind stale data check (required by TheForge protocol)
2. Shows any alerts (stale tasks, old questions, reminders, content alerts)
3. Optionally loads context for a specific project

## Usage

```
/forge-start              # Just run stale check
/forge-start ProjectName  # Stale check + load project context
```

## Instructions

When this skill is invoked:

### Step 1: Run the stale data check (REQUIRED)

```sql
SELECT 'STALE TASK' as alert, project_name, title, ROUND(days_stale) as days FROM v_stale_tasks
UNION ALL
SELECT 'OLD QUESTION', project_name, question, ROUND(days_open) FROM v_stale_questions
UNION ALL
SELECT 'REMINDER', COALESCE(project_name, 'General'), title, ROUND(days_until) FROM v_upcoming_reminders
UNION ALL
SELECT 'CONTENT LOW', platform, notes, posts_remaining FROM v_content_alerts;
```

### Step 2: Display alerts

If results found, display them grouped by type:
- **Overdue Reminders** (negative days_until)
- **Upcoming Reminders** (positive days_until)
- **Stale Tasks** (tasks not updated recently)
- **Old Questions** (unresolved questions)
- **Content Alerts** (low content warnings)

If no alerts, say "No alerts."

### Step 3: Load project context (if project name provided)

If user provided a project name as argument:

1. Find the project:
```sql
SELECT id, name, codename, status, description FROM projects
WHERE codename LIKE '%{arg}%' OR name LIKE '%{arg}%' LIMIT 1;
```

2. Load context:
```sql
SELECT summary, next_steps FROM session_notes WHERE project_id = ? ORDER BY session_date DESC LIMIT 1;
SELECT title, status, priority FROM tasks WHERE project_id = ? AND status IN ('todo', 'in_progress', 'blocked') ORDER BY priority DESC;
SELECT question FROM open_questions WHERE project_id = ? AND resolved = 0;
SELECT decision, rationale FROM decisions WHERE project_id = ? ORDER BY decided_at DESC LIMIT 3;
```

3. Read the project's CLAUDE.md file for technical context (use the project folder path from the projects table or the known mappings).

## Example Output

```
**Alerts:**
- REMINDER: Marketeer - Test Twitter posting fix (10 days overdue)
- OLD QUESTION: WipeStation - Bay count: 10 vs 12? (10 days)

**No project specified.** Use `/forge-start ProjectName` to load project context.
```
