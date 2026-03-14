# Project Rename: ProjectPombal → EQUIPA

**Date:** 2026-03-14
**Rationale:** Renamed to EQUIPA (European Portuguese for "team") - clean branding, zero AI-space collisions, self-explanatory meaning.

## Changes Made

### Claudinator (Linux)
- Renamed: `/srv/forge-share/AI_Stuff/ProjectPombal/` → `/srv/forge-share/AI_Stuff/Equipa/`
- Symlink: `theforge.db` still points to `/srv/forge-share/AI_Stuff/TheForge/theforge.db` (no change needed)
- No cron jobs found referencing old path
- No systemd services found referencing old path

### Windows
- Z:\AI_Stuff\ProjectPombal\ → Z:\AI_Stuff\Equipa\ (same network share, renamed on server side)

## Migration Notes
- All git worktrees under `.forge-worktrees/` moved automatically with folder rename
- TheForge database symlink remains functional
- No code changes needed (project uses relative paths and environment variables)
