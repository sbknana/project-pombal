#!/usr/bin/env python3
"""
Test suite for early termination signals in forge_orchestrator.py.

Tests verify:
1. _check_stuck_phrases detects stuck signal phrases correctly
2. _check_stuck_phrases is case-insensitive
3. _check_stuck_phrases returns None for clean text
4. _check_repeated_tool_calls detects 4 identical consecutive calls
5. _check_repeated_tool_calls returns False for varied calls
6. _check_repeated_tool_calls handles short history gracefully
7. EARLY_TERM_EXEMPT_ROLES includes all expected roles
8. EARLY_TERM_WARN_TURNS, EARLY_TERM_FINAL_WARN_TURNS, and EARLY_TERM_KILL_TURNS have correct values
9. _detect_tool_loop integrates correctly with early termination thresholds
10. Escalating warning thresholds are ordered correctly (warn < final_warn < kill)
11. Output hash computed for tool results (_compute_output_hash)
12. Same input + same output detected as stuck (stronger loop signal)
13. Same input + different output not flagged as stuck loop
14. Output hash handles None/empty content gracefully
15. Dead code _check_repeated_tool_calls removed
16. Alternating (A-B-A-B) loop detection triggers at 6+ failing alternations
17. Alternating loop warns at 4+ failing alternations
18. Successful alternating calls are not flagged
19. Mixed success/failure alternating patterns correctly detected
20. Three-way rotation (A-B-C) does not false-positive as alternating
21. Alternating detection coexists with consecutive detection

Copyright 2026 Forgeborn
"""

import hashlib
import sys
from pathlib import Path

# Add project root to path so we can import the orchestrator module
sys.path.insert(0, str(Path(__file__).parent))

from forge_orchestrator import (
    _check_stuck_phrases,
    _compute_output_hash,
    _detect_tool_loop,
    EARLY_TERM_WARN_TURNS,
    EARLY_TERM_FINAL_WARN_TURNS,
    EARLY_TERM_KILL_TURNS,
    EARLY_TERM_STUCK_PHRASES,
    EARLY_TERM_EXEMPT_ROLES,
)


# --- Tests for _check_stuck_phrases ---

def test_stuck_phrases_detects_each():
    """Test that each stuck phrase triggers a match."""
    for phrase in EARLY_TERM_STUCK_PHRASES:
        text = f"Here is some context. {phrase} So I will stop."
        matched = _check_stuck_phrases(text)
        assert matched is not None, f"no match for text containing '{phrase}'"
        # The match might be a shorter phrase that is a substring
        # (e.g., "i cannot" matches before "i cannot complete this task")
        # That's OK — we just need SOME match to fire
        assert matched in text.lower(), f"matched '{matched}' is not in text"


def test_stuck_phrases_case_insensitive():
    """Test that matching is case-insensitive."""
    result = _check_stuck_phrases("I AM UNABLE TO complete this task")
    assert result is not None, "should have matched uppercase 'I AM UNABLE TO'"

    result2 = _check_stuck_phrases("I Cannot access the file")
    assert result2 is not None, "should have matched mixed-case 'I Cannot'"


def test_stuck_phrases_returns_none_for_clean_text():
    """Test that clean text returns None."""
    clean_texts = [
        "I have successfully completed the task.",
        "The file was written to disk.",
        "Running tests now.",
        "Edit the configuration file.",
        "",
    ]
    for text in clean_texts:
        result = _check_stuck_phrases(text)
        assert result is None, f"expected None for '{text}', got '{result}'"


def test_stuck_phrases_partial_match():
    """Test that phrases embedded in longer words still match (substring match)."""
    # "i cannot" is in the phrase list - should match even in longer sentence
    result = _check_stuck_phrases("unfortunately i cannot proceed with this")
    assert result is not None, "should have matched 'i cannot' in sentence"


def test_stuck_phrases_returns_first_match():
    """Test that the first matching phrase is returned when multiple match."""
    # Text contains multiple stuck phrases
    text = "i am unable to do this and i'm stuck on the problem"
    result = _check_stuck_phrases(text)
    # Should return "i am unable to" since it comes first in the list
    assert result == "i am unable to", f"expected 'i am unable to', got '{result}'"


# --- Tests for dead code removal ---

def test_dead_code_removed():
    """Test that _check_repeated_tool_calls has been removed (dead code cleanup)."""
    import forge_orchestrator
    assert not hasattr(forge_orchestrator, "_check_repeated_tool_calls"), \
        "_check_repeated_tool_calls should be removed — it was dead code superseded by _detect_tool_loop"


# --- Tests for _compute_output_hash ---

def test_output_hash_computed_for_tool_results():
    """Test that _compute_output_hash returns a valid SHA256 hex digest."""
    # String content
    result = _compute_output_hash("Hello, world!")
    assert isinstance(result, str), f"expected str, got {type(result)}"
    assert len(result) == 64, f"expected 64-char SHA256 hex, got {len(result)} chars"
    expected = hashlib.sha256("Hello, world!".encode("utf-8")).hexdigest()
    assert result == expected, f"hash mismatch: {result} != {expected}"

    # List content (content blocks from Claude stream-json)
    list_content = [
        {"type": "text", "text": "file contents here"},
        {"type": "text", "text": "more text"},
    ]
    result2 = _compute_output_hash(list_content)
    assert isinstance(result2, str) and len(result2) == 64, \
        "list content should produce a valid SHA256 hex digest"
    # The hash should be of the space-joined text blocks
    expected2 = hashlib.sha256("file contents here more text".encode("utf-8")).hexdigest()
    assert result2 == expected2, f"list hash mismatch: {result2} != {expected2}"


def test_output_hash_handles_none_content():
    """Test that _compute_output_hash handles None and empty content."""
    # None content should return a deterministic hash (hash of empty string)
    result_none = _compute_output_hash(None)
    assert isinstance(result_none, str) and len(result_none) == 64, \
        "None content should produce a valid hash"

    # Empty string
    result_empty = _compute_output_hash("")
    assert isinstance(result_empty, str) and len(result_empty) == 64, \
        "empty string should produce a valid hash"

    # None and empty string should produce the same hash (both are empty)
    assert result_none == result_empty, \
        "None and empty string should hash identically"

    # Empty list
    result_empty_list = _compute_output_hash([])
    assert result_empty_list == result_empty, \
        "empty list should hash the same as empty string"

    # List with non-text blocks (should be skipped)
    result_no_text = _compute_output_hash([{"type": "image", "data": "..."}])
    assert result_no_text == result_empty, \
        "list with no text blocks should hash the same as empty content"


def test_same_input_same_output_detected_as_stuck():
    """Test that _detect_tool_loop flags same input + same output as a stronger stuck signal.

    When output hashes match alongside input signatures, the effective threshold
    should be lower (warn at 2, terminate at 3) because identical output confirms
    the agent is truly stuck rather than retrying with potential external changes.
    """
    history = ["Read|/foo.py"] * 3
    errors = ["error: file not found"] * 3
    # Same output hash for all 3 calls
    same_hash = hashlib.sha256(b"identical error output").hexdigest()
    output_hashes = [same_hash] * 3

    # With output hashes showing identical results, 3 repeats should terminate
    # (normally 3 repeats would only warn without output hash confirmation)
    action, count, sig = _detect_tool_loop(
        history, errors, tool_output_hashes=output_hashes,
        warn_threshold=3, terminate_threshold=5,
    )
    assert action == "terminate", \
        f"same input + same output at 3 repeats should terminate, got '{action}'"


def test_same_input_different_output_not_flagged():
    """Test that same input but different output does NOT trigger early termination.

    When the agent retries the same tool call but gets different output, it means
    external state has changed (e.g., file was created between retries). This should
    use the normal (higher) thresholds, not the output-hash-enhanced thresholds.
    """
    history = ["Bash|npm test"] * 4
    errors = ["error: test failed"] * 4
    # Different output hash each time (external state changing)
    output_hashes = [
        hashlib.sha256(f"output {i}".encode()).hexdigest()
        for i in range(4)
    ]

    # 4 repeats with different outputs should NOT terminate (threshold=5)
    action, count, sig = _detect_tool_loop(
        history, errors, tool_output_hashes=output_hashes,
        warn_threshold=3, terminate_threshold=5,
    )
    # Should warn (4 >= warn_threshold=3) but NOT terminate (4 < 5)
    assert action == "warn", \
        f"same input + different output at 4 repeats should warn, got '{action}'"
    assert count == 4, f"expected count 4, got {count}"


# --- Tests for constants ---

def test_constants_values():
    """Test that early termination constants have expected values."""
    assert EARLY_TERM_WARN_TURNS == 12, f"EARLY_TERM_WARN_TURNS should be 12, got {EARLY_TERM_WARN_TURNS}"
    assert EARLY_TERM_FINAL_WARN_TURNS == 18, f"EARLY_TERM_FINAL_WARN_TURNS should be 18, got {EARLY_TERM_FINAL_WARN_TURNS}"
    assert EARLY_TERM_KILL_TURNS == 22, f"EARLY_TERM_KILL_TURNS should be 22, got {EARLY_TERM_KILL_TURNS}"
    assert EARLY_TERM_WARN_TURNS < EARLY_TERM_FINAL_WARN_TURNS < EARLY_TERM_KILL_TURNS, \
        f"WARN_TURNS ({EARLY_TERM_WARN_TURNS}) < FINAL_WARN_TURNS ({EARLY_TERM_FINAL_WARN_TURNS}) < KILL_TURNS ({EARLY_TERM_KILL_TURNS})"


def test_exempt_roles_contains_expected():
    """Test that exempt roles include research/planning roles."""
    required_roles = {"planner", "evaluator", "security-reviewer", "code-reviewer", "researcher"}
    missing = required_roles - EARLY_TERM_EXEMPT_ROLES
    assert not missing, f"missing exempt roles: {missing}"

    # Developer and tester should NOT be exempt
    assert "developer" not in EARLY_TERM_EXEMPT_ROLES, "'developer' should NOT be exempt"
    assert "tester" not in EARLY_TERM_EXEMPT_ROLES, "'tester' should NOT be exempt"


def test_stuck_phrases_list_not_empty():
    """Test that stuck phrases list is populated."""
    assert EARLY_TERM_STUCK_PHRASES, "stuck phrases list is empty"
    assert len(EARLY_TERM_STUCK_PHRASES) >= 5, \
        f"expected at least 5 stuck phrases, got {len(EARLY_TERM_STUCK_PHRASES)}"

    # All phrases should be lowercase
    for phrase in EARLY_TERM_STUCK_PHRASES:
        assert phrase == phrase.lower(), f"phrase '{phrase}' is not lowercase"


# --- Tests for _detect_tool_loop integration ---

def test_detect_tool_loop_integrates_with_early_term():
    """Test _detect_tool_loop's terminate threshold catches stuck agents."""
    history = ["Bash|git status"] * 5
    errors = ["error"] * 5
    action, count, sig = _detect_tool_loop(history, errors)
    assert action == "terminate", f"expected 'terminate', got '{action}'"
    assert count == 5, f"expected count 5, got {count}"


def test_detect_tool_loop_warn_at_3():
    """Test _detect_tool_loop warns at 3 consecutive identical."""
    history = ["Read|/x.py"] * 3
    errors = ["error"] * 3
    action, count, sig = _detect_tool_loop(history, errors)
    assert action == "warn", f"expected 'warn', got '{action}'"


# --- Tests for alternating (A-B-A-B) loop detection ---

def test_alternating_pattern_detected_at_6_cycles():
    """Test that 6+ failing A-B alternations trigger 'terminate'."""
    # 6 alternations = 3 complete A-B pairs: A B A B A B
    history = []
    errors = []
    for _ in range(3):
        history.extend(["Read|/foo.py", "Edit|/foo.py"])
        errors.extend(["file not found", "edit failed"])
    # history is now 6 entries: A B A B A B, all failing
    action, count, sig = _detect_tool_loop(history, errors)
    assert action == "terminate", \
        f"expected 'terminate' for 6 failing alternations, got '{action}'"
    assert count >= 6, f"expected count >= 6, got {count}"


def test_alternating_pattern_warning_at_4_cycles():
    """Test that 4-5 failing A-B alternations trigger 'warn'."""
    # 4 alternations = 2 complete A-B pairs: A B A B
    history = []
    errors = []
    for _ in range(2):
        history.extend(["Grep|pattern", "Read|/src/main.py"])
        errors.extend(["no matches", "permission denied"])
    # history is 4 entries: A B A B, all failing
    action, count, sig = _detect_tool_loop(history, errors)
    assert action == "warn", \
        f"expected 'warn' for 4 failing alternations, got '{action}'"
    assert count >= 4, f"expected count >= 4, got {count}"


def test_alternating_successful_calls_not_flagged():
    """Test that alternating calls that SUCCEED are not flagged as stuck."""
    # 8 alternations but all successful
    history = []
    errors = []
    for _ in range(4):
        history.extend(["Read|/a.py", "Read|/b.py"])
        errors.extend([None, None])
    action, count, sig = _detect_tool_loop(history, errors)
    assert action == "ok", \
        f"expected 'ok' for successful alternations, got '{action}'"


def test_alternating_with_errors_flagged():
    """Test that alternating calls with errors are properly flagged."""
    # Mix: first 2 succeed, then 6 fail with alternating pattern
    history = ["Read|/a.py", "Read|/b.py"]  # these succeed
    errors = [None, None]
    for _ in range(3):
        history.extend(["Bash|npm test", "Edit|/fix.py"])
        errors.extend(["test failed", "syntax error"])
    # Last 6 entries are failing A-B-A-B-A-B
    action, count, sig = _detect_tool_loop(history, errors)
    assert action == "terminate", \
        f"expected 'terminate' for 6 failing alternations after successes, got '{action}'"


def test_three_way_rotation_not_false_positive():
    """Test that A-B-C-A-B-C rotation is NOT detected as A-B-A-B alternation."""
    # 9 entries: A B C A B C A B C — this is a 3-way pattern, not 2-way
    history = []
    errors = []
    for _ in range(3):
        history.extend(["Read|/a.py", "Edit|/b.py", "Bash|test"])
        errors.extend(["error", "error", "error"])
    action, count, sig = _detect_tool_loop(history, errors)
    # Should NOT trigger alternating detection — it's a 3-way rotation
    # The consecutive check also won't fire since they're all different
    assert action == "ok", \
        f"expected 'ok' for 3-way rotation, got '{action}'"


def test_alternating_detection_coexists_with_consecutive_detection():
    """Test that consecutive detection still works alongside alternating detection."""
    # Consecutive: 5 identical failing calls should still trigger terminate
    history = ["Bash|git status"] * 5
    errors = ["error: not a git repo"] * 5
    action, count, sig = _detect_tool_loop(history, errors)
    assert action == "terminate", \
        f"consecutive detection should still work, got '{action}'"
    assert count >= 5, f"expected count >= 5, got {count}"

    # Alternating: 6 failing A-B should also trigger terminate
    history2 = []
    errors2 = []
    for _ in range(3):
        history2.extend(["Read|/x", "Write|/x"])
        errors2.extend(["error", "error"])
    action2, count2, sig2 = _detect_tool_loop(history2, errors2)
    assert action2 == "terminate", \
        f"alternating detection should also work, got '{action2}'"


# --- Main ---

def main():
    tests = [
        test_stuck_phrases_detects_each,
        test_stuck_phrases_case_insensitive,
        test_stuck_phrases_returns_none_for_clean_text,
        test_stuck_phrases_partial_match,
        test_stuck_phrases_returns_first_match,
        test_dead_code_removed,
        test_output_hash_computed_for_tool_results,
        test_output_hash_handles_none_content,
        test_same_input_same_output_detected_as_stuck,
        test_same_input_different_output_not_flagged,
        test_constants_values,
        test_exempt_roles_contains_expected,
        test_stuck_phrases_list_not_empty,
        test_detect_tool_loop_integrates_with_early_term,
        test_detect_tool_loop_warn_at_3,
        test_alternating_pattern_detected_at_6_cycles,
        test_alternating_pattern_warning_at_4_cycles,
        test_alternating_successful_calls_not_flagged,
        test_alternating_with_errors_flagged,
        test_three_way_rotation_not_false_positive,
        test_alternating_detection_coexists_with_consecutive_detection,
    ]

    passed = 0
    failed = 0
    errors = []

    print(f"\n{'=' * 60}")
    print(f"  Early Termination Test Suite")
    print(f"  Testing _check_stuck_phrases, _compute_output_hash,")
    print(f"  _detect_tool_loop with output hashes, dead code removal")
    print(f"{'=' * 60}\n")

    for test_fn in tests:
        try:
            test_fn()
            passed += 1
            print(f"  PASS: {test_fn.__name__}")
        except AssertionError as e:
            print(f"  FAIL: {test_fn.__name__}: {e}")
            failed += 1
            errors.append(test_fn.__name__)
        except Exception as e:
            print(f"  ERROR: {test_fn.__name__}: {e}")
            failed += 1
            errors.append(f"{test_fn.__name__} (exception: {e})")

    print(f"\n{'=' * 60}")
    print(f"  Results: {passed} passed, {failed} failed out of {len(tests)}")
    if errors:
        print(f"  Failed tests: {', '.join(errors)}")
    print(f"{'=' * 60}\n")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
