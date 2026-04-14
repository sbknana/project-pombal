#!/bin/bash
# Auto-continue script: waits for 16 tasks to finish, then launches remaining 84
# Run on Claudinator

set -e
BENCHDIR="/srv/forge-share/AI_Stuff/Equipa/benchmarks"
LOG="/tmp/fb_verified_16.log"

echo "=== Waiting for 16-task run to complete ==="
while true; do
    PREDS=$(wc -l < "$BENCHDIR/fb_verified_16.jsonl" 2>/dev/null || echo 0)
    # Check if the process is still running
    if ! pgrep -f "featurebench_docker.py.*fb_verified_16" > /dev/null 2>&1; then
        echo "16-task run finished. Preds: $PREDS"
        break
    fi
    echo "$(date +%H:%M) Preds: $PREDS"
    sleep 120
done

echo "=== Launching remaining 84 tasks ==="
cd "$BENCHDIR"
python3 -u featurebench_docker.py \
    --limit 84 --offset 16 \
    --retries 10 --timeout 1800 \
    --output fb_verified_remaining84.jsonl \
    > /tmp/fb_verified_remaining84.log 2>&1

echo "=== 84-task run complete ==="
echo "Combining results..."
cat fb_verified_16.jsonl fb_verified_remaining84.jsonl > fb_verified_full100.jsonl
echo "Total predictions: $(wc -l < fb_verified_full100.jsonl)"
