# /forge-context

Load full context for a specific project from TheForge.

## What This Skill Does

1. Finds the project in TheForge database
2. Loads all relevant context (tasks, decisions, questions, last session)
3. Reads the project's CLAUDE.md for technical details
4. Displays a summary ready for work

## Usage

```
/forge-context YouTubeDownloader
/forge-context stampede
/forge-context 4                    # by project_id
```

## Instructions

When this skill is invoked with a project name or ID:

### Step 1: Find the project

```sql
-- If numeric, search by ID
SELECT id, name, codename, status, description, category FROM projects WHERE id = {arg};

-- If text, search by name/codename
SELECT id, name, codename, status, description, category FROM projects
WHERE codename LIKE '%{arg}%' OR name LIKE '%{arg}%' LIMIT 1;
```

If not found, list available projects:
```sql
SELECT id, codename, name, status FROM projects WHERE status != 'archived' ORDER BY id;
```

### Step 2: Load TheForge context

```sql
-- Last session notes
SELECT summary, next_steps, session_date FROM session_notes
WHERE project_id = ? ORDER BY session_date DESC LIMIT 1;

-- Active tasks
SELECT id, title, status, priority FROM tasks
WHERE project_id = ? AND status IN ('todo', 'in_progress', 'blocked')
ORDER BY priority DESC, id;

-- Open questions
SELECT id, question, context FROM open_questions
WHERE project_id = ? AND resolved = 0;

-- Recent decisions
SELECT decision, rationale, decided_at FROM decisions
WHERE project_id = ? ORDER BY decided_at DESC LIMIT 5;

-- Code artifacts
SELECT file_path, description FROM code_artifacts WHERE project_id = ?;
```

### Step 3: Read project CLAUDE.md

Query the project's `local_path` from TheForge to find its CLAUDE.md:

```sql
SELECT local_path FROM projects WHERE id = {project_id};
```

Then read: `{local_path}\CLAUDE.md`

If `local_path` is NULL, inform the user that the project folder path needs to be set in TheForge.

### Step 4: Display summary

Format the output as:

```
## {Project Name} (ID: {id})
**Status:** {status}
**Category:** {category}

### Last Session ({date})
{summary}

**Next Steps:**
{next_steps}

### Active Tasks
- [{status}] {title} (priority: {priority})

### Open Questions
- {question}

### Recent Decisions
- {decision} — {rationale}

---
*Technical context loaded from project CLAUDE.md*
```
