#!/bin/bash
# Auto-harness batch validator v2
# - Does NOT clear eval_outputs (harness skips already-evaluated tasks)
# - Only feeds NEW predictions each batch
# - Counts results from eval_outputs (source of truth)

BENCHDIR="/srv/forge-share/AI_Stuff/Equipa/benchmarks"
ORIG_PREDS="$BENCHDIR/fb_verified_16.jsonl"
NEW_PREDS="$BENCHDIR/fb_verified_remaining84.jsonl"
COMBINED="$BENCHDIR/fb_all_predictions.jsonl"
HARNESS_LOG="/tmp/fb_harness_v2.log"
LAST_EVALUATED=0

echo "=== Auto-Harness Batch Validator v2 ===" | tee "$HARNESS_LOG"
echo "$(date)" | tee -a "$HARNESS_LOG"

while true; do
    RUNNING=$(pgrep -f "featurebench_docker.py.*remaining84" > /dev/null && echo 1 || echo 0)
    NEW_COUNT=$(wc -l < "$NEW_PREDS" 2>/dev/null || echo 0)
    TOTAL_PREDS=$((16 + NEW_COUNT))

    # Every 5 new predictions, run harness on everything
    BATCH=$((TOTAL_PREDS / 5))
    EVALUATED_BATCH=$((LAST_EVALUATED / 5))

    if [ "$BATCH" -gt "$EVALUATED_BATCH" ] && [ "$TOTAL_PREDS" -gt "$LAST_EVALUATED" ]; then
        echo "" | tee -a "$HARNESS_LOG"
        echo "$(date) — $TOTAL_PREDS total predictions. Running harness..." | tee -a "$HARNESS_LOG"

        # Combine all predictions (don't clear eval_outputs!)
        cat "$ORIG_PREDS" "$NEW_PREDS" > "$COMBINED"
        cp "$COMBINED" "$BENCHDIR/output.jsonl"

        # Run harness — it auto-skips already evaluated tasks
        cd "$BENCHDIR/FeatureBench"
        python3 -m featurebench.harness.run_evaluation \
            --predictions-path ../output.jsonl \
            --split fast --n-concurrent 2 --timeout 600 \
            >> "$HARNESS_LOG" 2>&1

        LAST_EVALUATED=$TOTAL_PREDS

        # Count from eval_outputs (source of truth)
        echo "" | tee -a "$HARNESS_LOG"
        python3 -c "
import json, os
evaldir = '/srv/forge-share/AI_Stuff/Equipa/benchmarks/eval_outputs'
resolved = []
unresolved = []
repos = {}
for d in sorted(os.listdir(evaldir)):
    for attempt in ['attempt-1', 'attempt-2', 'attempt-3']:
        report = os.path.join(evaldir, d, attempt, 'report.json')
        if os.path.exists(report):
            with open(report) as f:
                r = json.load(f)
            data = list(r.values())[0] if isinstance(r, dict) and len(r) == 1 else r
            repo = d.split('.')[0].replace('__', '/')
            if repo not in repos:
                repos[repo] = {'r': 0, 'u': 0}
            if data.get('resolved'):
                resolved.append(d)
                repos[repo]['r'] += 1
            else:
                unresolved.append(d)
                repos[repo]['u'] += 1
            break

total = len(resolved) + len(unresolved)
print('=' * 50)
print(f'  VERIFIED: {len(resolved)} / {total} ({len(resolved)*100/total:.1f}%)')
print(f'  BENCHMARK SCORE: {len(resolved)}% (of 100 tasks)')
print('=' * 50)
print()
for repo, c in sorted(repos.items()):
    t = c['r'] + c['u']
    print(f'  {repo}: {c[\"r\"]}/{t}')
print()
print(f'Resolved: {[x[:45] for x in resolved]}')
" | tee -a "$HARNESS_LOG"
    fi

    # Exit when run is done
    if [ "$RUNNING" -eq 0 ]; then
        FINAL=$(wc -l < "$NEW_PREDS" 2>/dev/null || echo 0)
        FINAL_TOTAL=$((16 + FINAL))
        if [ "$FINAL_TOTAL" -le "$LAST_EVALUATED" ]; then
            echo "" | tee -a "$HARNESS_LOG"
            echo "$(date) — Run complete. Final evaluation done." | tee -a "$HARNESS_LOG"
            break
        fi
        # One final evaluation
        cat "$ORIG_PREDS" "$NEW_PREDS" > "$COMBINED"
        cp "$COMBINED" "$BENCHDIR/output.jsonl"
        cd "$BENCHDIR/FeatureBench"
        python3 -m featurebench.harness.run_evaluation \
            --predictions-path ../output.jsonl \
            --split fast --n-concurrent 4 --timeout 600 \
            >> "$HARNESS_LOG" 2>&1
        echo "$(date) — FINAL RUN COMPLETE" | tee -a "$HARNESS_LOG"
        break
    fi

    sleep 120
done
