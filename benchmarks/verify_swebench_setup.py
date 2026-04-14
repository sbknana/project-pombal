#!/usr/bin/env python3
"""
Verify SWE-bench setup is complete.

Checks:
1. swebench package installed
2. Dataset downloaded
3. Docker images pulled
"""

import json
import subprocess
import sys
from pathlib import Path

DATASET_PATH = Path(__file__).parent / "swebench_verified_full.jsonl"


def check_swebench_installed():
    """Check if swebench is installed."""
    try:
        result = subprocess.run(
            ["pip", "show", "swebench"],
            capture_output=True,
            text=True,
            check=True
        )
        version = [line for line in result.stdout.split('\n') if line.startswith('Version:')]
        print(f"✓ swebench installed: {version[0] if version else 'unknown version'}")
        return True
    except subprocess.CalledProcessError:
        print("✗ swebench NOT installed")
        return False


def check_dataset():
    """Check if dataset is downloaded."""
    if DATASET_PATH.exists():
        with open(DATASET_PATH) as f:
            count = sum(1 for _ in f)
        size_mb = DATASET_PATH.stat().st_size / (1024 * 1024)
        print(f"✓ Dataset downloaded: {count} instances, {size_mb:.1f} MB")
        return True, count
    else:
        print(f"✗ Dataset NOT found at {DATASET_PATH}")
        return False, 0


def check_docker_images():
    """Check how many SWE-bench Docker images are pulled."""
    try:
        result = subprocess.run(
            ["docker", "images", "--format", "{{.Repository}}"],
            capture_output=True,
            text=True,
            check=True
        )
        swebench_images = [
            line for line in result.stdout.split('\n')
            if 'swebench' in line.lower()
        ]
        print(f"✓ Docker images pulled: {len(swebench_images)} SWE-bench images")
        return True, len(swebench_images)
    except subprocess.CalledProcessError:
        print("✗ Could not query Docker images")
        return False, 0


def check_disk_usage():
    """Check disk usage in benchmarks directory."""
    try:
        result = subprocess.run(
            ["du", "-sh", str(Path(__file__).parent)],
            capture_output=True,
            text=True,
            check=True
        )
        usage = result.stdout.split()[0]
        print(f"ℹ Disk usage (benchmarks dir): {usage}")
    except subprocess.CalledProcessError:
        pass


def main():
    print("=== SWE-bench Setup Verification ===\n")

    all_ok = True

    # Check installation
    if not check_swebench_installed():
        all_ok = False

    # Check dataset
    dataset_ok, instance_count = check_dataset()
    if not dataset_ok:
        all_ok = False

    # Check Docker images
    images_ok, image_count = check_docker_images()
    if not images_ok:
        all_ok = False

    # Disk usage
    print()
    check_disk_usage()

    # Summary
    print("\n=== Summary ===")
    if all_ok:
        print("✓ SWE-bench setup complete")
        print(f"  - {instance_count} instances in dataset")
        print(f"  - {image_count} Docker images pulled")
        return 0
    else:
        print("✗ SWE-bench setup incomplete")
        return 1


if __name__ == "__main__":
    sys.exit(main())
