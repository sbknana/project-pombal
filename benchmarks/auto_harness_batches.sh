#!/bin/bash
# Auto-harness batch validator
# Runs harness every 5 completed predictions while EQUIPA continues
# Usage: Run alongside the main featurebench_docker.py run

BENCHDIR="/srv/forge-share/AI_Stuff/Equipa/benchmarks"
OUTPUT="$BENCHDIR/fb_verified_remaining84.jsonl"
HARNESS_LOG="/tmp/fb_harness_running.log"
TOTAL_VERIFIED=5  # Starting from our 16-task run verified count
TOTAL_TESTED=16   # Already tested 16
LAST_BATCH=0

echo "=== Auto-Harness Batch Validator ===" | tee "$HARNESS_LOG"
echo "Monitoring: $OUTPUT" | tee -a "$HARNESS_LOG"
echo "Starting verified count: $TOTAL_VERIFIED / $TOTAL_TESTED" | tee -a "$HARNESS_LOG"

while true; do
    # Check if the run is still going
    RUNNING=$(pgrep -f "featurebench_docker.py.*remaining84" > /dev/null && echo 1 || echo 0)
    PREDS=$(wc -l < "$OUTPUT" 2>/dev/null || echo 0)

    # Calculate which batch we're on (every 5 predictions)
    BATCH=$((PREDS / 5))

    if [ "$BATCH" -gt "$LAST_BATCH" ] && [ "$PREDS" -gt 0 ]; then
        BATCH_SIZE=$((BATCH * 5))
        echo "" | tee -a "$HARNESS_LOG"
        echo "$(date) — $PREDS predictions available. Running harness on first $BATCH_SIZE..." | tee -a "$HARNESS_LOG"

        # Copy predictions for harness
        head -"$BATCH_SIZE" "$OUTPUT" > "$BENCHDIR/fb_batch_current.jsonl"
        cp "$BENCHDIR/fb_batch_current.jsonl" "$BENCHDIR/output.jsonl"

        # Clear old eval outputs for these instances
        rm -rf "$BENCHDIR/eval_outputs/"*

        # Run harness
        cd "$BENCHDIR/FeatureBench"
        python3 -m featurebench.harness.run_evaluation \
            --predictions-path ../output.jsonl \
            --split fast --n-concurrent 2 --timeout 600 \
            >> "$HARNESS_LOG" 2>&1

        # Extract results
        BATCH_RESOLVED=$(grep -oP "Resolved: \K[0-9]+" "$HARNESS_LOG" | tail -1)
        BATCH_TOTAL=$(grep -oP "Total: \K[0-9]+" "$HARNESS_LOG" | tail -1)
        BATCH_RATE=$(grep -oP "Resolved rate: \K[0-9.]+" "$HARNESS_LOG" | tail -1)
        BATCH_F2P=$(grep -oP "Avg F2P pass rate: \K[0-9.]+" "$HARNESS_LOG" | tail -1)

        # Running totals (add to the 5 verified from first 16 tasks)
        RUNNING_VERIFIED=$((5 + BATCH_RESOLVED))
        RUNNING_TOTAL=$((16 + BATCH_SIZE))

        echo "" | tee -a "$HARNESS_LOG"
        echo "======================================" | tee -a "$HARNESS_LOG"
        echo "  BATCH RESULT ($BATCH_SIZE new tasks)" | tee -a "$HARNESS_LOG"
        echo "  This batch: $BATCH_RESOLVED/$BATCH_TOTAL ($BATCH_RATE%)" | tee -a "$HARNESS_LOG"
        echo "  F2P pass rate: $BATCH_F2P%" | tee -a "$HARNESS_LOG"
        echo "  RUNNING TOTAL: $RUNNING_VERIFIED/$RUNNING_TOTAL verified" | tee -a "$HARNESS_LOG"
        echo "======================================" | tee -a "$HARNESS_LOG"

        LAST_BATCH=$BATCH
    fi

    # Exit if run is done and we've processed all predictions
    if [ "$RUNNING" -eq 0 ]; then
        FINAL_PREDS=$(wc -l < "$OUTPUT" 2>/dev/null || echo 0)
        if [ "$FINAL_PREDS" -le "$((LAST_BATCH * 5))" ] || [ "$FINAL_PREDS" -eq 0 ]; then
            echo "" | tee -a "$HARNESS_LOG"
            echo "$(date) — Run complete. Running final harness on all $FINAL_PREDS predictions..." | tee -a "$HARNESS_LOG"

            if [ "$FINAL_PREDS" -gt "$((LAST_BATCH * 5))" ]; then
                cp "$OUTPUT" "$BENCHDIR/output.jsonl"
                rm -rf "$BENCHDIR/eval_outputs/"*
                cd "$BENCHDIR/FeatureBench"
                python3 -m featurebench.harness.run_evaluation \
                    --predictions-path ../output.jsonl \
                    --split fast --n-concurrent 2 --timeout 600 \
                    >> "$HARNESS_LOG" 2>&1
            fi

            # Combine all results
            echo "" | tee -a "$HARNESS_LOG"
            echo "=== COMBINING ALL RESULTS ===" | tee -a "$HARNESS_LOG"
            cat "$BENCHDIR/fb_verified_16.jsonl" "$OUTPUT" > "$BENCHDIR/fb_verified_full100.jsonl"
            FULL_PREDS=$(wc -l < "$BENCHDIR/fb_verified_full100.jsonl")
            echo "Combined file: fb_verified_full100.jsonl ($FULL_PREDS predictions)" | tee -a "$HARNESS_LOG"

            # Final harness on everything
            echo "Running FINAL harness on all $FULL_PREDS predictions..." | tee -a "$HARNESS_LOG"
            cp "$BENCHDIR/fb_verified_full100.jsonl" "$BENCHDIR/output.jsonl"
            rm -rf "$BENCHDIR/eval_outputs/"*
            cd "$BENCHDIR/FeatureBench"
            python3 -m featurebench.harness.run_evaluation \
                --predictions-path ../output.jsonl \
                --split fast --n-concurrent 4 --timeout 600 \
                >> "$HARNESS_LOG" 2>&1

            echo "" | tee -a "$HARNESS_LOG"
            echo "=== ALL DONE ===" | tee -a "$HARNESS_LOG"
            tail -10 "$HARNESS_LOG"
            break
        fi
    fi

    sleep 120
done
