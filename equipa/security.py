"""EQUIPA security — untrusted content isolation and skill integrity.

Layer 5: Imports from equipa.constants only.

Copyright 2026 Forgeborn
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from pathlib import Path

from equipa.constants import PROMPTS_DIR, SKILL_MANIFEST_FILE, SKILLS_BASE_DIR


def _make_untrusted_delimiter() -> str:
    """Return a unique, unpredictable delimiter for untrusted content markers."""
    return f"UNTRUSTED_{uuid.uuid4().hex[:8]}"


def wrap_untrusted(content: str, delimiter: str) -> str:
    """Wrap *content* in unpredictable untrusted-content markers.

    The delimiter is generated once per prompt build and shared across all
    injection sites so the agent sees a single, consistent boundary token.
    """
    return f"<<<{delimiter}>>>\n{content}\n<<<END_{delimiter}>>>"


def generate_skill_manifest() -> dict[str, str]:
    """Scan all prompt and skill .md files and return a dict of {relative_path: sha256_hex}.

    Used by --regenerate-manifest to create/update skill_manifest.json.
    """
    base_dir = Path(__file__).parent.parent
    manifest: dict[str, str] = {}

    # Collect all .md files from prompts/ and skills/
    for search_dir in [PROMPTS_DIR, SKILLS_BASE_DIR]:
        if not search_dir.is_dir():
            continue
        for md_file in sorted(search_dir.rglob("*.md")):
            rel_path = str(md_file.relative_to(base_dir))
            file_hash = hashlib.sha256(md_file.read_bytes()).hexdigest()
            manifest[rel_path] = file_hash

    return manifest


def write_skill_manifest() -> dict:
    """Generate and write skill_manifest.json to the repo root."""
    manifest = generate_skill_manifest()
    manifest_data = {
        "version": 1,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "description": "SHA-256 hashes of prompt and skill files for integrity verification",
        "files": manifest,
    }
    SKILL_MANIFEST_FILE.write_text(
        json.dumps(manifest_data, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {len(manifest)} file hashes to {SKILL_MANIFEST_FILE}")
    return manifest_data


def verify_skill_integrity() -> bool:
    """Verify all prompt and skill files match known-good SHA-256 hashes.

    Returns True if verification passes (or manifest is missing for backward compat).
    Returns False if any file has been tampered with or is missing.
    """
    if not SKILL_MANIFEST_FILE.exists():
        print("WARNING: skill_manifest.json not found — skipping integrity check "
              "(generate with --regenerate-manifest)")
        return True  # backward compat: missing manifest is not a blocker

    try:
        manifest_data = json.loads(SKILL_MANIFEST_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        print(f"CRITICAL: Failed to load skill_manifest.json: {e}")
        return False

    expected_files = manifest_data.get("files", {})
    if not expected_files:
        print("CRITICAL: skill_manifest.json contains no file entries — refusing to dispatch")
        return False

    base_dir = Path(__file__).parent.parent
    mismatches: list[str] = []
    missing: list[str] = []

    for rel_path, expected_hash in expected_files.items():
        file_path = base_dir / rel_path
        if not file_path.exists():
            missing.append(rel_path)
            continue
        actual_hash = hashlib.sha256(file_path.read_bytes()).hexdigest()
        if actual_hash != expected_hash:
            mismatches.append(rel_path)

    if missing:
        print(f"CRITICAL: Skill integrity check FAILED — {len(missing)} file(s) missing:")
        for f in missing:
            print(f"  MISSING: {f}")

    if mismatches:
        print(f"CRITICAL: Skill integrity check FAILED — {len(mismatches)} file(s) modified:")
        for f in mismatches:
            print(f"  TAMPERED: {f}")

    if missing or mismatches:
        print("CRITICAL: Agent dispatch BLOCKED — skill files do not match manifest. "
              "If changes are intentional, run: python forge_orchestrator.py --regenerate-manifest")
        return False

    return True
