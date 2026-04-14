# Email Draft — FeatureBench Submission

**To:** qixingzhou1125@gmail.com, zjcheng2022@gmail.com
**From:** forgeborn.dev@gmail.com
**Subject:** FeatureBench Submission — EQUIPA (54% on fast split)

---

Hi there,

Submitting our results for the FeatureBench leaderboard. We're EQUIPA, a multi-agent orchestrator built by Forgeborn.

**Score: 54/100 (54%) on the fast split (Level 1).**

Quick rundown of the setup:
- Developer agent on Claude Opus, tester agent on Claude Sonnet
- Custom orchestrator running a dev-test loop with up to 10 retries per task
- Each task runs inside your official Docker containers
- Patches extracted via git diff against the masked baseline

The eval report is attached. The predictions JSONL is ~700MB (some patches are bloated — more on that below), so I couldn't attach it. Two options, whatever works best for you:

1. I can host it on our site at forgeborn.dev for you to download
2. If you have a preferred upload method (HuggingFace, Google Drive, etc.) just let me know

**One thing worth flagging** — we ran into a patch extraction issue on large repos (scikit-learn, seaborn, pandas, mlflow, etc.). When agents run tests inside the Docker containers, it triggers builds that modify tracked files.. venv installs, Cython compilation, .so rebuilds, that sort of thing. A `git diff` after the agent finishes ends up capturing all of that noise — we had patches ballooning to 50-97MB when the actual fix was 1-3 files.

12 of our 100 tasks hit this. The agent solved them (tests passed inside the container), but the extracted patches were too large for the harness to apply. So our real solve rate is probably closer to 57-60%, but we're submitting the 54% as verified.

This might affect other agents too — anyone running inside those Docker images and extracting a git diff will pick up the same build artifacts. A couple of ideas that might help:

1. The harness could filter incoming patches to only include source files (by extension) before applying them
2. Or apply patches with something like `git apply --include='*.py' --include='*.pyi'`
3. A patch size warning/cap would catch this early

Not a complaint at all — FeatureBench is a solid benchmark and we enjoyed running it. Just figured it's worth mentioning in case it's tripping up others.

Happy to share the EQUIPA source code or discuss the architecture if useful. Let us know if you need anything else for the submission.

Cheers,
Forgeborn
forgeborn.dev@gmail.com
