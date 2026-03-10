# /forge-search

Universal search across all TheForge tables.

## What This Skill Does

Searches for a term across all major TheForge tables:
- tasks
- decisions
- session_notes
- open_questions
- projects
- code_artifacts

## Usage

```
/forge-search authentication
/forge-search "USB cloning"
/forge-search error handling
```

## Instructions

When this skill is invoked with a search term:

### Step 1: Run universal search

Replace `{term}` with the user's search term:

```sql
SELECT 'project' as source, id, name as title, description as context, NULL as project_id
FROM projects WHERE name LIKE '%{term}%' OR description LIKE '%{term}%' OR codename LIKE '%{term}%'

UNION ALL

SELECT 'task', id, title, description, project_id
FROM tasks WHERE title LIKE '%{term}%' OR description LIKE '%{term}%'

UNION ALL

SELECT 'decision', id, decision, rationale, project_id
FROM decisions WHERE decision LIKE '%{term}%' OR rationale LIKE '%{term}%' OR alternatives LIKE '%{term}%'

UNION ALL

SELECT 'session_note', id, summary, next_steps, project_id
FROM session_notes WHERE summary LIKE '%{term}%' OR next_steps LIKE '%{term}%'

UNION ALL

SELECT 'question', id, question, context, project_id
FROM open_questions WHERE question LIKE '%{term}%' OR context LIKE '%{term}%'

UNION ALL

SELECT 'artifact', id, file_path, description, project_id
FROM code_artifacts WHERE file_path LIKE '%{term}%' OR description LIKE '%{term}%'

ORDER BY source, id DESC
LIMIT 50;
```

### Step 2: Get project names for results

```sql
SELECT id, name, codename FROM projects;
```

### Step 3: Display results grouped by type

Format output as:

```
## Search Results for "{term}"

### Projects
- **{name}** (ID: {id}) — {description}

### Tasks
- [{project_name}] {title} (ID: {id}, status: {status})

### Decisions
- [{project_name}] {decision} — {rationale}

### Session Notes
- [{project_name}] {summary}

### Open Questions
- [{project_name}] {question}

### Code Artifacts
- [{project_name}] {file_path} — {description}

---
{count} results found
```

### Step 4: Offer to load full context

If results found, offer:
"Want me to load full context for any of these? Use `/forge-context {project_name}`"
