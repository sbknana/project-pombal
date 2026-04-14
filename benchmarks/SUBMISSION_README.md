# EQUIPA FeatureBench Submission

## Agent: EQUIPA (by Forgeborn)

**Score: 54/100 (54%) on FeatureBench fast split (Level 1)**

## Architecture

EQUIPA is a multi-agent orchestrator that coordinates developer and tester agents in an iterative dev-test loop.

- **Developer agent**: Claude Opus (claude-opus-4-20250514) — writes code, makes commits
- **Tester agent**: Claude Sonnet (claude-sonnet-4-20250514) — runs tests, validates
- **Orchestrator**: Custom Python orchestrator managing agent lifecycle, context engineering, and retry logic
- **Execution**: Each task runs inside the official FeatureBench Docker container with isolated git worktrees

## Pipeline

1. Pull FeatureBench Docker image for the repo
2. Set up masked state (apply masking patch, remove f2p test files, create git baseline)
3. Install EQUIPA agent inside the container
4. Run dev-test loop: developer writes fix → tester validates → retry if needed
5. Extract git diff from agent's commits as model_patch
6. Up to 10 retry attempts per task with 1800s timeout

## Files

- `fb_EQUIPA_SUBMISSION_54pct.jsonl` — 100 predictions (JSONL, one per FeatureBench fast split task)
- `fb_EQUIPA_report.json` — Harness evaluation report from official FeatureBench evaluator
- `SUBMISSION_README.md` — This file

## Results Breakdown

| Metric | Value |
|--------|-------|
| Total tasks | 100 |
| Resolved | 54 |
| Unresolved | 34 |
| Patch not applied | 12 |
| Resolved rate | 54% |

## Known Issue: Large Repo Patch Extraction

12 tasks produced bloated patches (12-97MB) because the agent's `git add -A` captured build artifacts and venv files in large repos (scikit-learn, seaborn, pandas, mlflow, astropy, hatch, setuptools). The agent solved these tasks inside the Docker container (tests passed), but the extracted patches are too large for the harness to apply.

We believe this affects all agents running in these Docker containers, not just EQUIPA. See the accompanying email for details and a suggested harness improvement.

## Reproducibility

Source code: https://github.com/sbknana/equipa (private — available on request)
Runner script: `featurebench_docker.py` in the EQUIPA benchmarks directory

## Contact

Forgeborn — forgeborn.dev@gmail.com
