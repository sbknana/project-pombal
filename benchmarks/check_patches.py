#!/usr/bin/env python3
"""Check what our patches actually contain."""
import json

with open("output.jsonl") as f:
    for line in f:
        d = json.loads(line)
        iid = d["instance_id"]
        patch = d["model_patch"]
        files = [l for l in patch.split("\n") if l.startswith("diff --git")]
        adds = sum(1 for l in patch.split("\n") if l.startswith("+") and not l.startswith("+++"))
        dels = sum(1 for l in patch.split("\n") if l.startswith("-") and not l.startswith("---"))
        print(f"{iid[:55]}:")
        for fl in files:
            print(f"  {fl}")
        print(f"  +{adds} -{dels} lines, {len(patch)} chars total")
        print()
