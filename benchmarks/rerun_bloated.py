#!/usr/bin/env python3
"""Re-run the 12 FeatureBench tasks that produced bloated patches (>500KB).

These tasks resolved inside Docker but produced 12-97MB patches because
git add -A captured build artifacts. The fix in featurebench_docker.py
now filters patches to source code only.

This script re-runs ONLY those 12 tasks and outputs to fb_rerun_bloated.jsonl.
After completion, merge with the clean predictions from fb_SUBMISSION.jsonl
to produce the final submission.

Copyright 2026 Forgeborn
"""
import json
import sys
import subprocess

SUBMISSION = "fb_SUBMISSION.jsonl"
OUTPUT = "fb_rerun_bloated.jsonl"
SIZE_THRESHOLD = 500_000  # 500KB

def get_bloated_offsets():
    """Find which line offsets in the submission have bloated patches."""
    offsets = []
    with open(SUBMISSION) as f:
        for i, line in enumerate(f):
            d = json.loads(line)
            if len(d.get("model_patch", "")) > SIZE_THRESHOLD:
                offsets.append(i)
                print(f"  [{i}] {d['instance_id'][:65]} "
                      f"({len(d['model_patch'])/1e6:.1f}MB)")
    return offsets

def main():
    print(f"Scanning {SUBMISSION} for bloated patches (>{SIZE_THRESHOLD/1e6:.1f}MB)...")
    offsets = get_bloated_offsets()
    print(f"\nFound {len(offsets)} bloated tasks.")

    if not offsets:
        print("Nothing to re-run.")
        return

    # Re-run each one individually (different repos need different Docker images)
    for offset in offsets:
        print(f"\n{'='*60}")
        print(f"  Re-running offset {offset}...")
        print(f"{'='*60}")
        cmd = [
            sys.executable, "-u", "featurebench_docker.py",
            "--limit", "1",
            "--offset", str(offset),
            "--retries", "10",
            "--timeout", "1800",
            "--output", f"fb_rerun_{offset}.jsonl",
        ]
        result = subprocess.run(cmd)
        if result.returncode != 0:
            print(f"  WARNING: offset {offset} failed (exit {result.returncode})")

    # Merge individual results
    print(f"\n{'='*60}")
    print(f"  Merging results into {OUTPUT}")
    print(f"{'='*60}")
    results = {}
    for offset in offsets:
        fname = f"fb_rerun_{offset}.jsonl"
        try:
            with open(fname) as f:
                for line in f:
                    d = json.loads(line)
                    results[d["instance_id"]] = d
                    size = len(d.get("model_patch", ""))
                    print(f"  {d['instance_id'][:55]}: {size/1e3:.1f}KB")
        except FileNotFoundError:
            print(f"  MISSING: {fname}")

    # Write merged output
    with open(OUTPUT, "w") as f:
        for d in results.values():
            f.write(json.dumps(d) + "\n")
    print(f"\nWrote {len(results)} predictions to {OUTPUT}")

    # Build final submission: replace bloated entries with re-run results
    final_count = 0
    replaced = 0
    with open(SUBMISSION) as fin, open("fb_FINAL_SUBMISSION.jsonl", "w") as fout:
        for line in fin:
            d = json.loads(line)
            iid = d["instance_id"]
            if iid in results:
                fout.write(json.dumps(results[iid]) + "\n")
                replaced += 1
            else:
                fout.write(line)
            final_count += 1
    print(f"Final submission: {final_count} tasks ({replaced} replaced)")
    print(f"Output: fb_FINAL_SUBMISSION.jsonl")

if __name__ == "__main__":
    main()
