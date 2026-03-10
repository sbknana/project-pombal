# /forge-update

Full update protocol for TheForge. Updates both the database AND relevant CLAUDE.md files.

## What This Skill Does

When significant changes are made to a project, this skill ensures:
1. TheForge database is updated (tasks, decisions, session_notes, etc.)
2. The project's CLAUDE.md is updated with new info
3. TheForge's main CLAUDE.md Known Projects table is updated (if needed)

## Usage

```
/forge-update                    # Interactive - will ask what to update
/forge-update YouTubeDownloader  # Update specific project
```

## Instructions

### When to use this skill

Use `/forge-update` when:
- A project's status changes (planning → active → complete)
- Major architecture decisions are made
- New key files or features are added
- A new project is created
- Project documentation needs syncing with TheForge

### Step 1: Identify what to update

Ask: "What changed? (new project / project status / key decision / new feature / other)"

### Step 2: Update TheForge database

**For new project:**
```sql
INSERT INTO projects (name, codename, description, status, category, created_at)
VALUES ('{name}', '{codename}', '{description}', '{status}', '{category}', CURRENT_TIMESTAMP);
```

**For status change:**
```sql
UPDATE projects SET status = '{new_status}' WHERE id = {project_id};
```

**For key decision:**
```sql
INSERT INTO decisions (project_id, decision, rationale, alternatives, decided_at)
VALUES ({project_id}, '{decision}', '{rationale}', '{alternatives}', CURRENT_TIMESTAMP);
```

### Step 3: Update project CLAUDE.md

Read the project's CLAUDE.md file and update relevant sections:
- Version numbers
- Status
- Key features
- Architecture changes
- Build commands
- Important files

**Get project folder from DB:**
```sql
SELECT local_path FROM projects WHERE id = {project_id};
```

### Step 4: Update TheForge CLAUDE.md (if needed)

Only update TheForge's main `CLAUDE.md` if:
- New project added (update Known Projects table)
- Project status changed significantly
- Project folder location changed

**Do NOT duplicate detailed project info in TheForge CLAUDE.md** — that belongs in the project's own CLAUDE.md.

### Step 5: Confirm updates

Display:
```
Updates completed:
- TheForge DB: {what was updated}
- {Project} CLAUDE.md: {what was updated}
- TheForge CLAUDE.md: {updated / no changes needed}
```

## Important Rules

1. **Project CLAUDE.md is the source of truth** for technical details
2. **TheForge CLAUDE.md** only has the Known Projects table and protocols
3. **Never duplicate** detailed project info in both places
4. **Always update the project's CLAUDE.md** when making significant changes
