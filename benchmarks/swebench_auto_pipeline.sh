#!/bin/bash
# SWE-bench Verified — Continuous Pipeline v2
# Runs batch on swebench VM -> copies JSONL -> harness on Claudinator -> next batch
# (c) 2026 Forgeborn

BENCHDIR="/srv/forge-share/AI_Stuff/Equipa/benchmarks"
BATCH_SIZE=10
TIMEOUT=1800
LOG="/tmp/swebench_auto_pipeline.log"

source ~/.bashrc

# Completed offsets (step 10, batch size 10)
# 55,65,75,85,95,105,115,125,135,145,155,165,175,185,195,205,215,225,235,245
# Plus batch 0 is running now
# Remaining: 10,20,30,40,50 + 255,265,275,...,490

REMAINING="10 20 30 40 50 255 265 275 285 295 305 315 325 335 345 355 365 375 385 395 405 415 425 435 445 455 465 475 485 495"

echo "$(date) — SWE-bench Auto Pipeline v2 Starting" | tee "$LOG"
echo "Remaining offsets: $REMAINING" | tee -a "$LOG"
echo "Total remaining batches: $(echo $REMAINING | wc -w)" | tee -a "$LOG"
echo "" | tee -a "$LOG"

# Wait for batch0 to finish first
echo "Waiting for batch0 to complete..." | tee -a "$LOG"
while ssh swebench 'pgrep -f "swebench_runner.*offset.0" > /dev/null 2>&1'; do
    sleep 30
done
echo "Batch0 done. Running harness..." | tee -a "$LOG"

# Harness batch0
JSONL_EXISTS=$(ssh swebench "test -f ~/equipa/benchmarks/swebench_host_batch0.jsonl && echo yes || echo no")
if [ "$JSONL_EXISTS" = "yes" ]; then
    scp swebench:~/equipa/benchmarks/swebench_host_batch0.jsonl "$BENCHDIR/swebench_host_batch0.jsonl"
    python3 -m swebench.harness.run_evaluation \
        --predictions_path "$BENCHDIR/swebench_host_batch0.jsonl" \
        --run_id "equipa_batch0" \
        --max_workers 4 --timeout 300 >> "$LOG" 2>&1
    echo "  Batch0 harness complete" | tee -a "$LOG"
fi

# Also harness batch245 (completed earlier, not yet verified)
JSONL245=$(test -f "$BENCHDIR/swebench_host_batch245.jsonl" && echo yes || echo no)
if [ "$JSONL245" = "yes" ]; then
    echo "Running harness on batch245..." | tee -a "$LOG"
    python3 -m swebench.harness.run_evaluation \
        --predictions_path "$BENCHDIR/swebench_host_batch245.jsonl" \
        --run_id "equipa_batch245" \
        --max_workers 4 --timeout 300 >> "$LOG" 2>&1
    echo "  Batch245 harness complete" | tee -a "$LOG"
fi

for OFFSET in $REMAINING; do
    BATCH_NAME="batch${OFFSET}"
    echo "" | tee -a "$LOG"
    echo "$(date) — [$BATCH_NAME] Starting offset $OFFSET" | tee -a "$LOG"

    # Phase 1: Run batch on swebench VM
    echo "  [1/3] Running EQUIPA on swebench VM..." | tee -a "$LOG"
    ssh swebench "cd ~/equipa/benchmarks && \
        export THEFORGE_DB=/home/user/equipa/theforge.db && \
        python3 -u swebench_runner.py \
            --limit $BATCH_SIZE --offset $OFFSET \
            --timeout $TIMEOUT \
            --output swebench_host_${BATCH_NAME}.json" \
        >> "$LOG" 2>&1

    # Check if JSONL was produced
    JSONL_EXISTS=$(ssh swebench "test -f ~/equipa/benchmarks/swebench_host_${BATCH_NAME}.jsonl && echo yes || echo no")
    if [ "$JSONL_EXISTS" != "yes" ]; then
        echo "  WARNING: No JSONL for $BATCH_NAME, skipping harness" | tee -a "$LOG"
        continue
    fi

    # Phase 2: Copy to Claudinator
    echo "  [2/3] Copying results..." | tee -a "$LOG"
    scp swebench:~/equipa/benchmarks/swebench_host_${BATCH_NAME}.jsonl \
        "$BENCHDIR/swebench_host_${BATCH_NAME}.jsonl" >> "$LOG" 2>&1

    # Phase 3: Run harness
    echo "  [3/3] Running harness..." | tee -a "$LOG"
    python3 -m swebench.harness.run_evaluation \
        --predictions_path "$BENCHDIR/swebench_host_${BATCH_NAME}.jsonl" \
        --run_id "equipa_${BATCH_NAME}" \
        --max_workers 4 \
        --timeout 300 \
        >> "$LOG" 2>&1

    # Quick tally
    HARNESS_RESOLVED=0
    HARNESS_TOTAL=0
    for rpt in "$BENCHDIR/logs/run_evaluation/equipa_${BATCH_NAME}"/*/*/report.json; do
        if [ -f "$rpt" ]; then
            res=$(python3 -c "import json; r=json.load(open('$rpt')); print(sum(1 for v in r.values() if v.get('resolved')))")
            tot=$(python3 -c "import json; r=json.load(open('$rpt')); print(len(r))")
            HARNESS_RESOLVED=$((HARNESS_RESOLVED + res))
            HARNESS_TOTAL=$((HARNESS_TOTAL + tot))
        fi
    done
    if [ "$HARNESS_TOTAL" -gt 0 ]; then
        echo "  Harness: $HARNESS_RESOLVED/$HARNESS_TOTAL" | tee -a "$LOG"
    fi
done

echo "" | tee -a "$LOG"
echo "$(date) — ALL BATCHES COMPLETE" | tee -a "$LOG"
echo "=== FINAL TALLY ===" | tee -a "$LOG"
cd "$BENCHDIR" && python3 /tmp/tally_harness2.py 2>/dev/null | tee -a "$LOG"
