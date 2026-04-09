#!/usr/bin/env python3
"""Format EQUIPA results for FeatureBench harness validation."""
import json

with open("featurebench_harness_validation.json") as f:
    d = json.load(f)

count = 0
with open("output.jsonl", "w") as f:
    for r in d["results"]:
        patch = r.get("patch", "")
        iid = r["instance_id"]
        if patch:
            pred = {
                "instance_id": iid,
                "model_patch": patch,
                "model_name_or_path": "EQUIPA (Opus 4.6 dev + Sonnet tester, dev-test loops, autoresearch)",
                "n_attempt": r.get("attempts", 1),
                "success": True,
            }
            f.write(json.dumps(pred) + "\n")
            count += 1
            print(f"  OK: {iid[:60]} ({len(patch)} chars)")
        else:
            print(f"  SKIP: {iid[:60]} (no patch)")

print(f"\nFormatted {count} predictions to output.jsonl")
