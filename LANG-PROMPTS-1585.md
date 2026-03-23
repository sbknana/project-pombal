# Task 1585: Language-Specific Agent Prompts

## Summary

Added language-specific prompt injection to EQUIPA so agents receive tailored coding guidelines based on the detected project language.

## Changes Made

### 1. Enhanced `detect_project_language()` (forge_orchestrator.py:5712)

**Before:** Returned a plain string (`"python"`, `"dotnet"`, `"node"`, or `"default"`).

**After:** Returns a dict with three keys:
- `languages`: list of all detected languages (e.g., `["typescript", "python"]`)
- `frameworks`: list of detected frameworks (e.g., `["nextjs", "react"]`)
- `primary`: the first/most prominent language detected

**Detected languages (7):**
| Language | Marker Files |
|----------|-------------|
| python | pyproject.toml, setup.py, requirements.txt, Pipfile, *.py |
| typescript | tsconfig.json |
| javascript | package.json (without tsconfig.json) |
| go | go.mod |
| rust | Cargo.toml |
| csharp | *.csproj, *.sln |
| java | pom.xml, build.gradle, build.gradle.kts |

**Detected frameworks:**
- Python: django, fastapi, flask (from pyproject.toml)
- JS/TS: nextjs, react, express, vue, angular (from package.json)
- C#: dotnet (from *.csproj/*.sln)
- Java: maven, gradle (from build files)

### 2. Created `prompts/languages/` Directory (4 files)

| File | Content Summary |
|------|----------------|
| `python.md` | PEP 8, type hints, mutable default args, bare except, async patterns, pytest idioms |
| `typescript.md` | strict mode, `any` abuse, async correctness, React patterns (framework-conditional), null safety |
| `go.md` | error wrapping, goroutine leaks, context.Context, defer patterns, table-driven tests |
| `csharp.md` | async/await, IDisposable, LINQ, nullable reference types, DI patterns |

### 3. Injection in `build_system_prompt()` (forge_orchestrator.py:~2284)

After task-type supplement injection and before budget visibility:
- Calls `detect_project_language(project_dir)` to detect the project's languages
- For each detected language with a matching `prompts/languages/{lang}.md` file, reads and appends the prompt
- If frameworks are detected (excluding build-system names like dotnet/maven/gradle), appends a note telling the agent to apply framework-specific patterns
- Handles multi-language projects (e.g., a project with both Python and TypeScript)
- Silently skips languages without a prompt file (e.g., rust, java, javascript)

### 4. Updated Callers

Updated `setup_single_repo()` (two call sites at lines ~5846, ~5850) to use the new dict return format, mapping new language keys to existing `GITIGNORE_TEMPLATES` keys.

## Test Results

All **288 tests passed** in 4.66s with 1 deprecation warning (pre-existing asyncio event loop warning).

## LOC Impact

- ~90 lines in forge_orchestrator.py (73 new detection function + 17 injection logic)
- ~190 lines across 4 markdown files
- Total: ~280 lines added
