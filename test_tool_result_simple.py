#!/usr/bin/env python3
"""Standalone test for tool_result_storage module (bypasses broken package imports)."""

import sys
import tempfile
from pathlib import Path

# Import module directly without going through package __init__.py
sys.path.insert(0, str(Path(__file__).parent))
import importlib.util
spec = importlib.util.spec_from_file_location(
    "tool_result_storage",
    Path(__file__).parent / "equipa" / "tool_result_storage.py"
)
trs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(trs)

# Run tests
print("Testing tool_result_storage module...")

# Test 1: format_file_size
assert trs.format_file_size(512) == "512B"
assert trs.format_file_size(1024) == "1.0KB"
assert trs.format_file_size(1024 * 1024) == "1.0MB"
print("✓ format_file_size works")

# Test 2: generate_preview
content = "Line 1\nLine 2\nLine 3\n" * 100
preview, has_more = trs.generate_preview(content, 200)
assert has_more is True
assert len(preview) <= 200
print("✓ generate_preview works")

# Test 3: persist_tool_result
with tempfile.TemporaryDirectory() as tmpdir:
    content_str = "Test output\n" * 100
    filepath, size, is_json, preview, has_more = trs.persist_tool_result(
        content_str, "tool-test-1", tmpdir
    )
    assert filepath.exists()
    assert size == len(content_str)
    assert is_json is False
    print("✓ persist_tool_result works")

# Test 4: maybe_persist_large_result (small)
with tempfile.TemporaryDirectory() as tmpdir:
    small_content = "Small output"
    result = trs.maybe_persist_large_result(small_content, "tool-2", tmpdir)
    assert result == small_content
    print("✓ maybe_persist_large_result (small) works")

# Test 5: maybe_persist_large_result (large)
with tempfile.TemporaryDirectory() as tmpdir:
    large_content = "x" * 60_000
    result = trs.maybe_persist_large_result(large_content, "tool-3", tmpdir)
    assert isinstance(result, str)
    assert result != large_content
    assert trs.PERSISTED_OUTPUT_TAG in result
    print("✓ maybe_persist_large_result (large) works")

# Test 6: process_agent_output
with tempfile.TemporaryDirectory() as tmpdir:
    raw_output = "Result line\n" * 10_000  # ~120KB
    result = trs.process_agent_output(raw_output, "agent-1", tmpdir)
    assert result != raw_output
    assert trs.PERSISTED_OUTPUT_TAG in result
    print("✓ process_agent_output works")

# Test 7: is_content_already_compacted
normal = "Regular text"
compacted = f"{trs.PERSISTED_OUTPUT_TAG}\nStuff\n{trs.PERSISTED_OUTPUT_CLOSING_TAG}"
assert trs.is_content_already_compacted(normal) is False
assert trs.is_content_already_compacted(compacted) is True
print("✓ is_content_already_compacted works")

print("\n✅ All 7 tests passed!")
