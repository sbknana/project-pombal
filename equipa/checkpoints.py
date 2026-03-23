"""EQUIPA checkpoint save/load/clear for agent resume on retry.

Extracted from forge_orchestrator.py as part of Phase 1 monolith split.
All functions are re-exported via equipa/__init__.py for backward compatibility.

Copyright 2026 Forgeborn
"""

from __future__ import annotations

from pathlib import Path

from equipa.constants import CHECKPOINT_DIR


def save_checkpoint(
    task_id: int,
    attempt: int,
    output_text: str,
    role: str = "developer",
) -> Path | None:
    """Save agent output to a checkpoint file for resume on retry.

    Returns the checkpoint file path.
    """
    CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"task_{task_id}_{role}_attempt_{attempt}.txt"
    filepath = CHECKPOINT_DIR / filename
    try:
        filepath.write_text(output_text, encoding="utf-8")
    except OSError as e:
        print(f"  [Checkpoint] WARNING: Failed to save checkpoint: {e}")
        return None
    return filepath


def load_checkpoint(
    task_id: int,
    role: str = "developer",
) -> tuple[str | None, int]:
    """Load the most recent checkpoint for a task+role.

    Returns (checkpoint_text, attempt_number) or (None, 0) if no checkpoint exists.
    """
    if not CHECKPOINT_DIR.exists():
        return None, 0

    # Find all checkpoints for this task+role, sorted by attempt number
    pattern = f"task_{task_id}_{role}_attempt_*.txt"
    checkpoints = sorted(CHECKPOINT_DIR.glob(pattern))
    if not checkpoints:
        return None, 0

    latest = checkpoints[-1]
    try:
        text = latest.read_text(encoding="utf-8")
    except OSError:
        return None, 0

    # Extract attempt number from filename
    stem = latest.stem  # e.g. task_124_developer_attempt_2
    try:
        attempt = int(stem.rsplit("_", 1)[1])
    except (ValueError, IndexError):
        attempt = 0

    return text, attempt


def clear_checkpoints(task_id: int, role: str | None = None) -> None:
    """Remove checkpoint files for a completed task."""
    if not CHECKPOINT_DIR.exists():
        return
    if role:
        pattern = f"task_{task_id}_{role}_attempt_*.txt"
    else:
        pattern = f"task_{task_id}_*_attempt_*.txt"
    for f in CHECKPOINT_DIR.glob(pattern):
        try:
            f.unlink()
        except OSError:
            pass
