# /housekeeping

Weekly hygiene check. Keeps files lean, flags bloat, cleans stale artifacts.

## Usage

```
/housekeeping        # Run all checks, report findings
/housekeeping fix    # Run checks AND auto-fix what's safe to fix
```

## Instructions

When this skill is invoked, run ALL checks below and present a summary report.

### Check 1: File Size Limits

Find the MEMORY.md and CLAUDE.md files for the current project and count their lines:

| File | Limit |
|------|-------|
| MEMORY.md (auto-memory) | 150 lines |
| Project CLAUDE.md | 200 lines |

Also check ALL topic files in the memory directory — flag any over **100 lines**.

### Check 2: Plan File Hygiene

Look for plan files (usually in a plans directory or `.claude/plans/`). Check:
1. **Missing STATUS header** — first non-blank line should start with `## STATUS:`
2. **Stale plans** — files with `## STATUS: ACTIVE` older than 30 days
3. **Completed plans not cleaned** — files with `## STATUS: COMPLETE` older than 14 days can be deleted

If `fix` argument provided: delete completed plans older than 14 days.

### Check 3: Projects Missing local_path

```sql
SELECT id, codename, status FROM projects WHERE local_path IS NULL AND status IN ('active', 'planning');
```

Report any results. These projects can't be auto-located.

### Check 4: MEMORY.md Topic Index Sync

If MEMORY.md has a "Topic File Index" section, compare against actual files in the memory directory. Flag:
- **Orphaned files** — exist on disk but not listed in the index
- **Dead links** — listed in index but file doesn't exist

If `fix` argument provided: add missing files to the index, remove dead links.

### Check 5: Content in Wrong Places

Scan MEMORY.md for patterns that belong in separate topic files:
- IP addresses with port numbers (deployment details)
- Credentials or password references
- Long code blocks (should be in code_artifacts table or topic files)

Flag any matches with line numbers.

### Check 6: DB-Duplicated Content in CLAUDE.md

Scan CLAUDE.md for hardcoded project lists that should be DB queries:
- Lines matching `| NUMBER |` pattern (table rows with project IDs)
- More than 3 consecutive `|` table rows (likely a hardcoded list)

Flag if found.

## Report Format

```
## Housekeeping Report — {date}

### File Sizes
| File | Lines | Limit | Status |
|------|-------|-------|--------|
| MEMORY.md | 124 | 150 | OK |
| CLAUDE.md | 195 | 200 | OK |

### Plan Files: {count} total
- {count} active, {count} complete, {count} missing STATUS header

### Projects Missing local_path: {count}
### Topic Index: {orphaned} orphaned, {dead} dead links
### Content Leaks: {count} misplaced patterns in MEMORY.md
### DB Duplication: {count} hardcoded lists in CLAUDE.md

### Actions Needed:
1. ...
2. ...
```

## Philosophy

**If the DB stores it, query it. If it's done, delete it. Every line must earn its place.**
