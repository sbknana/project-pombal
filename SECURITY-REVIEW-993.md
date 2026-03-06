# Security Review — Task #993

**Project:** Project Pombal (project_id: 23)
**Date:** 2026-03-06
**Reviewer:** SecurityReviewer agent (Task #993)
**Scope:** Security review of test suite written for the Project Pombal orchestrator
**Finding Prefix:** TS (Test Suite)

## Executive Summary

Reviewed 11 test files (test_agent_actions.py, test_early_termination.py, test_loop_detection.py, test_task_type_routing.py, test_lessons_injection.py, test_episode_injection.py, test_lesson_sanitizer.py, test_agent_messages.py, test_forgesmith_simba.py, test_rubric_scoring.py, test_rubric_quality_scorer.py) plus the associated source files (lesson_sanitizer.py, rubric_quality_scorer.py, forge_orchestrator.py, forgesmith.py, forgesmith_simba.py, db_migrate.py).

**Total Findings: 17** (0 CRITICAL, 2 HIGH, 5 MEDIUM, 5 LOW, 5 INFO)

## Findings

---

### TS-01 | HIGH | Tests modify production database directly

**Files:** `test_episode_injection.py:50-110`, `test_lessons_injection.py:27-53`, `test_forgesmith_simba.py:58-164`

**Description:** Three test files (test_episode_injection.py, test_lessons_injection.py, test_forgesmith_simba.py) connect to and modify the **production** TheForge database (`THEFORGE_DB`) directly. They INSERT test data, DELETE existing data, and UPDATE records in production tables (`agent_episodes`, `lessons_learned`).

**Impact:**
- `test_lessons_injection.py:31` executes `DELETE FROM lessons_learned` (line 31) — this **wipes ALL production lessons** before inserting test data
- `test_episode_injection.py:57` deletes episodes with `task_id >= 9000`, which could collide with real data as the system grows
- `test_forgesmith_simba.py:67-68` deletes episodes and lessons matching test patterns
- If tests are run in production or by CI, real lesson/episode data is destroyed
- Q-value updates in test_episode_injection.py permanently alter production episode q_values (lines 280, 310, 345, 369)

**Severity Rationale:** Data corruption of production database. Lessons drive agent behavior — wiping them degrades agent quality system-wide.

**Recommendation:**
- Use isolated temporary databases (like test_agent_messages.py and test_rubric_quality_scorer.py already do correctly)
- Never `DELETE FROM <table>` without a WHERE clause scoped to test data
- Use `tempfile.mkstemp()` to create test-only databases
- Mock `THEFORGE_DB` to point to temp databases during tests

---

### TS-02 | HIGH | pytest CVE-2025-71176: privilege escalation via predictable temp paths

**File:** System dependency (pytest 9.0.2)

**Description:** The installed pytest version 9.0.2 is vulnerable to CVE-2025-71176 (CVSS 6.8). The vulnerability involves predictable `/tmp/pytest-of-{user}` directory paths, allowing local attackers to exploit symlink races for DoS or privilege escalation on UNIX systems.

**Impact:** A local attacker with access to the shared `/srv/forge-share/` filesystem could exploit the predictable pytest temp directory to inject malicious content or perform privilege escalation when tests are run.

**Recommendation:** Upgrade pytest past version 9.0.2.

---

### TS-03 | MEDIUM | Test data IDs risk collision with production data

**Files:** `test_episode_injection.py:60-100`, `test_forgesmith_simba.py:71-109`

**Description:** Test data uses hardcoded task_id ranges (9000-9999 for episodes, 8000-8099 for SIMBA) that could collide with real task IDs as the system grows. The `tasks` table auto-increments, and production data will eventually reach these ranges.

**Impact:** When production task_ids reach the 8000-9999 range, test cleanup operations (`DELETE FROM agent_episodes WHERE task_id >= 9000`) will destroy real production data.

**Recommendation:**
- Use negative task_ids for test data (e.g., -9001, -9002) which cannot collide with auto-increment
- Or use isolated temporary databases as recommended in TS-01
- Or use task_ids in a much higher range (e.g., 999000+) and document the reservation

---

### TS-04 | MEDIUM | Exception handler typo: `AssertionError` vs `AssertionError`

**Files:** `test_lesson_sanitizer.py:361`, `test_early_termination.py:225`, `test_episode_injection.py:554`, `test_lessons_injection.py:289`, `test_agent_actions.py:524`, `test_agent_messages.py:460`

**Description:** Six test files catch `AssertionError` (typo) instead of `AssertionError`. In Python, `AssertionError` is NOT a built-in exception — it will be treated as a `NameError` at runtime, causing the except clause to fail silently. This means assertion failures in the custom test runners will be swallowed and appear as generic `Exception` errors instead.

**Impact:** Test failures are misreported, making it harder to diagnose broken security invariants. The custom test runners (non-pytest mode) will not properly distinguish assertion failures from other exceptions, masking test failures.

**Note:** When these tests are run via pytest (as some are designed to be), this issue doesn't manifest because pytest catches assertions directly. But the standalone `python3 test_*.py` runners are affected.

**Recommendation:** Fix all instances of `AssertionError` to `AssertionError`:
- `test_lesson_sanitizer.py:361`
- `test_early_termination.py:225`
- `test_episode_injection.py:554`
- `test_lessons_injection.py:289`
- `test_agent_actions.py:524`
- `test_agent_messages.py:460`

---

### TS-05 | MEDIUM | Connection leak confirmed in rubric_quality_scorer.py (QS-01 still open)

**File:** `rubric_quality_scorer.py:361-380`

**Description:** The `store_quality_scores()` function opens a sqlite3 connection (line 361) and calls `conn.close()` at line 380, but the close is NOT inside a `finally` block. If `conn.execute()` (line 362) or `conn.commit()` (line 379) raises an exception, the connection is leaked. The test `test_store_returns_false_on_missing_table` (test_rubric_quality_scorer.py:386-401) tests the failure path but does not verify that the connection was properly closed.

**Impact:** Connection leaks can exhaust file descriptors under load, leading to `sqlite3.OperationalError: unable to open database file` failures that are difficult to diagnose.

**Recommendation:** Use a context manager or try/finally:
```python
conn = sqlite3.connect(str(db_path))
try:
    conn.execute(...)
    conn.commit()
    return True
except Exception as e:
    logger.warning(...)
    return False
finally:
    conn.close()
```

---

### TS-06 | MEDIUM | Test reads production source code to verify patterns

**File:** `test_task_type_routing.py:93-115`

**Description:** `test_orchestrator_injection_logic()` reads the full source code of `forge_orchestrator.py` and pattern-matches against it to verify implementation. This is a fragile testing approach that:
1. Couples tests to source code text patterns (not behavior)
2. Opens an attack surface: an attacker who can modify `forge_orchestrator.py` could embed injection payloads that pass the pattern check while changing behavior
3. Provides no behavioral verification — a function could contain the text patterns but be dead code

**Impact:** Low direct security impact, but tests that verify patterns rather than behavior create a false sense of security. The task_type injection logic could be broken while these tests still pass.

**Recommendation:** Replace source-code text matching with behavioral tests — call `build_system_prompt()` with different task_types and assert the output contains the expected guidance text.

---

### TS-07 | MEDIUM | Sanitizer tests have weak assertion logic for role overrides

**File:** `test_lesson_sanitizer.py:86-87`

**Description:** The assertion for role override stripping uses `or` logic:
```python
assert "ignore previous" not in result.lower() or "instruction" not in result.lower()
```
This assertion passes if EITHER condition is true. So if `result` contains the full phrase "ignore previous instructions", the assertion still passes because it checks each fragment independently with OR. The assertion should use AND logic to verify both fragments are removed.

**Impact:** The test may pass even when the sanitizer fails to strip role override phrases, giving false confidence in the injection prevention.

**Recommendation:** Change to AND logic:
```python
assert "ignore previous" not in result.lower() and "instruction" not in result.lower()
```
Or better, check for the full phrase: `assert "ignore previous instructions" not in result.lower()`

---

### TS-08 | LOW | Temporary files not cleaned up on test failure

**Files:** `test_agent_messages.py:35-38`, `test_rubric_scoring.py:350-364`

**Description:** `test_agent_messages.py` creates temporary database files via `tempfile.NamedTemporaryFile(suffix=".db", delete=False)` but cleanup in `teardown_test_db()` uses `missing_ok=True` which silently ignores missing files. While the try/finally pattern is used, if the process is killed mid-test, temp files persist in `/tmp/`. Similarly, `test_rubric_scoring.py:350-364` creates checkpoint files in `.forge-checkpoints/` that may persist on test failure.

**Impact:** Accumulated temp files in `/tmp/` and `.forge-checkpoints/` consume disk space and could contain test data (including simulated database contents).

**Recommendation:** Use `tempfile.TemporaryDirectory()` context managers where possible. Ensure `.forge-checkpoints/` test files are cleaned in tearDown.

---

### TS-09 | LOW | Tests swallow all exceptions in "never crashes" test pattern

**Files:** `test_agent_actions.py:276-290,363-374`, and their corresponding source functions

**Description:** Several tests verify that functions "never crash" by ensuring no exception is raised (test_log_agent_action_never_crashes, test_bulk_log_agent_actions_never_crashes, test_get_action_summary_never_crashes). While this tests the design intent, the source functions catch `Exception` broadly:
- `log_agent_action` swallows all exceptions
- `bulk_log_agent_actions` swallows all exceptions
- `get_action_summary` returns `{}` on any error

The tests validate this pattern but the pattern itself is PM-41 (swallowing 26+ exceptions across the codebase). The tests do NOT distinguish between expected exceptions (DB errors) and unexpected ones (programming errors, KeyError, TypeError).

**Impact:** If a programming error is introduced (e.g., wrong column name), it will be silently swallowed by both the code and the tests, making bugs harder to detect.

**Recommendation:** The source functions should catch `sqlite3.Error` specifically (not bare `Exception`). Tests should verify that non-DB exceptions ARE propagated.

---

### TS-10 | LOW | test_rubric_scoring.py sets THEFORGE_DB env var without restoring

**File:** `test_rubric_scoring.py:36`

**Description:** Both `TestRubricScoring.setUp()` and `TestRubricEvolution.setUp()` set `os.environ["THEFORGE_DB"]` to a temp path but do NOT restore the original environment variable in `tearDown()`. While the temp file is cleaned up, the environment variable persists, potentially affecting subsequent test runs or other test files if run in the same process.

**Impact:** Cross-test contamination. If another test file reads `THEFORGE_DB` from environment after this test runs, it will get a deleted database path.

**Recommendation:** Save and restore the original `THEFORGE_DB`:
```python
def setUp(self):
    self._original_theforge_db = os.environ.get("THEFORGE_DB")
    ...
def tearDown(self):
    if self._original_theforge_db is not None:
        os.environ["THEFORGE_DB"] = self._original_theforge_db
    elif "THEFORGE_DB" in os.environ:
        del os.environ["THEFORGE_DB"]
```

---

### TS-11 | LOW | f-string SQL query construction in test_episode_injection.py

**Files:** `test_episode_injection.py:457`, `test_lessons_injection.py:233-235`

**Description:** Two test files construct SQL queries using f-strings with `','.join('?' * len(ids))`:
```python
f"SELECT id, q_value FROM agent_episodes WHERE task_id IN ({','.join('?' * len(episode_ids))})"
```
While the parameterized values are passed separately (preventing SQL injection), the f-string pattern is a code smell that could be copied by developers unfamiliar with SQL injection and modified to include actual values instead of placeholders.

**Impact:** No direct vulnerability (values are parameterized correctly), but the pattern is easy to misuse if copied.

**Recommendation:** Consider using a helper function for constructing IN clause queries, or add a comment explaining why this specific pattern is safe.

---

### TS-12 | LOW | Python 3.12.3 has 11+ CVEs including tarfile bypass and use-after-free

**File:** System dependency

**Description:** The Python runtime is version 3.12.3 (April 2024), which has at least 11 known CVEs fixed in later 3.12.x releases:
- CVE-2024-12718 (HIGH): tarfile extraction filter bypass via symlinks
- CVE-2025-4138 (HIGH): Use-after-free in "unicode-escape" decoder
- CVE-2025-4330 (HIGH): tarfile extraction filter bypass via crafted symlinks
- CVE-2024-6232 (MEDIUM): tarfile header parsing ReDoS
- CVE-2024-6923 (MEDIUM): Email header spoofing
- CVE-2024-7592 (MEDIUM): DoS in http.cookies
- CVE-2024-8088 (MEDIUM): DoS in zipfile
- CVE-2024-9287: venv privilege escalation
- CVE-2024-12254: HTTP response unlimited Content-Length

**Impact:** While Project Pombal doesn't directly use tarfile/zipfile, the orchestrator's `auto_install_dependencies` function runs `pip install` which processes tar/zip archives internally. The unicode-escape vulnerability could affect any string processing.

**Recommendation:** Upgrade to Python 3.12.11 or later.

---

### TS-13 | INFO | No conftest.py for shared test fixtures

**File:** (Missing)

**Description:** The project has 11 test files but no `conftest.py` to provide shared fixtures. Several test files duplicate similar setup patterns:
- 3 files create temp databases independently
- 4 files use `sys.path.insert(0, str(Path(__file__).parent))` identically
- Multiple files reimplement database cleanup patterns

**Impact:** Code duplication increases the risk of inconsistent cleanup and makes it harder to enforce security-relevant test patterns (like always using temp databases).

**Recommendation:** Create a `conftest.py` with shared fixtures for:
- Temporary database creation and cleanup
- Production database isolation
- Common test data factories

---

### TS-14 | INFO | Sanitizer test does not cover nested/encoded injection vectors

**File:** `test_lesson_sanitizer.py`

**Description:** The sanitizer tests cover basic injection vectors (XML tags, role overrides, base64, ANSI escapes) but do not test:
- Nested injection: `<<system>system>injection<</system>/system>`
- HTML entity encoding: `&lt;system&gt;`
- Unicode homoglyphs: Using lookalike characters to bypass regex
- Mixed-case tag with attributes: `<SyStEm class="x">`
- Zero-width characters inserted between injection keywords
- Markdown injection: `[link](javascript:alert(1))`

**Impact:** An attacker who can control agent output could potentially bypass the sanitizer with encoded or nested injection attempts.

**Recommendation:** Add test cases for:
- Double-nested tags
- HTML entity encoded tags
- Unicode lookalike characters (e.g., Cyrillic а instead of Latin a)
- Zero-width joiner/non-joiner characters within keywords
- Verify regex handles all edge cases of `re.IGNORECASE`

---

### TS-15 | INFO | No test isolation between custom test runners

**Files:** All test files with `main()` or `run_all_tests()` functions

**Description:** Most test files implement custom test runners (not pytest) that run tests sequentially. Tests that modify global state (e.g., `_injected_episodes_by_task.clear()` in test_episode_injection.py:406) can affect subsequent tests. There is no mechanism to reset global state between tests in the custom runners.

**Impact:** Intermittent test failures that depend on execution order. A test that passes in isolation might fail when run after another test that modified global state.

**Recommendation:** Standardize on pytest with proper fixtures for setup/teardown. Remove custom test runners.

---

### TS-16 | INFO | Jinja2 3.1.2, setuptools 68.1.2, pip 24.0 have HIGH-severity CVEs

**File:** System dependencies (not directly imported by Project Pombal)

**Description:** Several system-wide Python packages have known HIGH-severity CVEs:
- **Jinja2 3.1.2**: 4 CVEs including CVE-2024-56201 (CVSS 8.8, arbitrary code execution) and CVE-2024-56326/CVE-2025-27516 (sandbox escape)
- **setuptools 68.1.2**: CVE-2025-47273 (CVSS 8.8, path traversal to arbitrary file write → RCE)
- **pip 24.0**: CVE-2025-8869 (CVSS 5.9, symlink path traversal in tar extraction)

While Project Pombal does not directly import these packages, they are used by the Python ecosystem (pip, package installation, CI tooling) and their vulnerabilities are relevant because the orchestrator runs `pip install` via `auto_install_dependencies()`.

**Impact:** The setuptools path traversal vulnerability is particularly relevant: when `auto_install_dependencies()` runs `pip install -r requirements.txt`, pip uses setuptools internally. A malicious package in requirements.txt could exploit CVE-2025-47273 to write arbitrary files.

**Recommendation:** Upgrade: Jinja2 → 3.1.6+, setuptools → 78.1.1+, pip → 25.3+.

---

### TS-17 | INFO | No dependency manifest file exists

**File:** (Missing: no requirements.txt, pyproject.toml, setup.py, or Pipfile)

**Description:** Project Pombal has no dependency manifest file. While the project uses primarily standard library modules, the absence of a manifest means:
1. Builds are not reproducible
2. Version pinning is impossible
3. Dependency confusion attacks cannot be detected by scanning tools
4. It's unclear which system packages are actually required

**Impact:** Operational risk. Cannot run automated vulnerability scanning against declared dependencies.

**Recommendation:** Create a minimal `pyproject.toml` or `requirements.txt` listing at minimum:
```
# Runtime: stdlib only (no third-party deps)
# Test: pytest>=9.1 (must be past CVE-2025-71176)
```

---

## Summary Table

| ID | Severity | Title | Status |
|----|----------|-------|--------|
| TS-01 | HIGH | Tests modify production database directly | OPEN |
| TS-02 | HIGH | pytest CVE-2025-71176 privilege escalation | OPEN |
| TS-03 | MEDIUM | Test data IDs risk collision with production | OPEN |
| TS-04 | MEDIUM | AssertionError typo in 6 test files | OPEN |
| TS-05 | MEDIUM | Connection leak in rubric_quality_scorer.py (QS-01 re-confirmed) | OPEN |
| TS-06 | MEDIUM | Test reads source code patterns instead of testing behavior | OPEN |
| TS-07 | MEDIUM | Weak assertion logic for role override sanitization | OPEN |
| TS-08 | LOW | Temporary files not cleaned up on test failure | OPEN |
| TS-09 | LOW | Tests validate exception swallowing pattern (PM-41) | OPEN |
| TS-10 | LOW | THEFORGE_DB env var not restored after test | OPEN |
| TS-11 | LOW | f-string SQL pattern in test code | OPEN |
| TS-12 | LOW | Python 3.12.3 has 11+ known CVEs | OPEN |
| TS-13 | INFO | No conftest.py for shared test fixtures | OPEN |
| TS-14 | INFO | Sanitizer tests missing encoded injection vectors | OPEN |
| TS-15 | INFO | No test isolation in custom test runners | OPEN |
| TS-16 | INFO | Jinja2/setuptools/pip system deps have HIGH CVEs | OPEN |
| TS-17 | INFO | No dependency manifest file | OPEN |

## Positive Observations

1. **test_rubric_quality_scorer.py uses proper test isolation** — creates temporary databases with `tempfile.mkstemp()`, cleans up in `tearDown()` (good pattern to follow)
2. **test_agent_messages.py uses proper test isolation** — patches `THEFORGE_DB` to temp path and restores in finally blocks
3. **test_agent_actions.py uses in-memory databases** — the `_NoCloseConnection` wrapper pattern is clever and avoids production DB modification
4. **test_lesson_sanitizer.py tests the full injection pipeline** — end-to-end test from malicious error_summary through to formatted output (test_combined_pipeline_security)
5. **All SQL in source code uses parameterized queries** — no SQL injection vulnerabilities found
6. **Mocking pattern is well-executed** — `unittest.mock.patch` is used correctly in test_agent_actions.py and test_forgesmith_simba.py

## Prior Findings Status

The following prior findings were re-verified during this review:
- **QS-01 (HIGH → re-confirmed as TS-05 MEDIUM)**: Connection leak in `store_quality_scores()` — still present, conn.close() not in finally block
- **PM-41 (LOW → re-confirmed as TS-09)**: Exception swallowing pattern validated by tests but not fixed
- **PM-38 (MEDIUM)**: Supply-chain risk from `auto_install_dependencies` — now compounded by CVE-2025-47273 in setuptools (TS-16)

## ClaudeStick Security Tools Applied

| Tool | Application | Result |
|------|-------------|--------|
| audit-context-building | Mapped trust boundaries, data flows, and injection points across all 11 test files and 6 source files | Trust boundary at lesson sanitizer pipeline; production DB access boundary violated by 3 test files |
| static-analysis | Semgrep unavailable in environment (no pip). Manual pattern analysis substituted | Identified TS-04 typo pattern, TS-07 weak assertion, TS-11 f-string SQL |
| variant-analysis | Searched for the production-DB-modification anti-pattern across all test files | Found 3 files modify production DB (TS-01); 3 files properly isolated (positive) |
| differential-review | Compared test isolation patterns across all 11 test files | Identified split: 3 files use prod DB, 4 use temp DB, 4 use in-memory — inconsistent |
| fix-review | Verified whether prior security findings (QS-01, PM-41) were addressed in test code | Neither fixed; QS-01 re-confirmed, PM-41 validated-but-not-fixed |
| semgrep-rule-creator | Cannot run (semgrep not available). Would create rules for: prod-DB-in-tests, AssertionError typo, bare-except-in-tests | N/A — environment limitation |
| sharp-edges | Identified dangerous API patterns: direct sqlite3.connect to THEFORGE_DB in tests, os.environ mutation without restore, sys.path.insert | Documented as TS-01, TS-10, TS-13 |

---

*Review performed by SecurityReviewer agent. All findings are OPEN and should be prioritized for remediation.*
