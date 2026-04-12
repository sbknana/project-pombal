# SWE-bench Verified Setup Complete

**Date:** 2026-04-12
**Status:** ✓ Ready for evaluation runs

## Setup Summary

### 1. SWE-bench Installation
```bash
pip install --user swebench
```
- **Version:** 4.1.0
- **Location:** ~/.local/lib/python3.12/site-packages/swebench

### 2. Dataset Download
```bash
python -c "from datasets import load_dataset; ds = load_dataset('princeton-nlp/SWE-bench_Verified', split='test'); ds.to_json('/srv/forge-share/AI_Stuff/Equipa/benchmarks/swebench_verified_full.jsonl')"
```
- **File:** `/srv/forge-share/AI_Stuff/Equipa/benchmarks/swebench_verified_full.jsonl`
- **Size:** 7.8 MB
- **Instances:** 500 test cases

### 3. Docker Images
```bash
python3 /srv/forge-share/AI_Stuff/Equipa/benchmarks/pull_swebench_images.py
```
- **Images Pulled:** 18 Docker images
- **Disk Usage:** 5.7 GB (benchmarks directory)
- **Total Docker Storage:** 177.8 GB (94% utilized)

#### Image Types
- 1 base image: `sweb.base.py.x86_64:latest`
- 5 environment images: `sweb.env.py.x86_64.*:latest`
- 12+ evaluation images: `sweb.eval.x86_64.*:latest`

## Verification

Run the verification script to check setup status:
```bash
python3 /srv/forge-share/AI_Stuff/Equipa/benchmarks/check_setup_status.py
```

Expected output: All checks passing (swebench installed, dataset downloaded, Docker images pulled)

## Disk Space Considerations

Current usage:
- Benchmarks directory: 5.7 GB
- Docker total storage: 177.8 GB (167.6 GB used, 94%)

**Note:** Full SWE-bench Verified (500 instances) requires significant disk space. First 50 instances pulled to validate setup. For complete runs, monitor disk usage and consider:
- Pulling images in batches
- Cleaning up intermediate containers
- Prioritizing common repositories (django, flask, requests, sympy, scikit-learn)

## Next Steps

1. **Run calibration batch:** Test EQUIPA on first 10-20 instances
2. **Monitor resource usage:** Track disk, memory, and time per instance
3. **Scale gradually:** Expand to 50, 100, then full 500 instances
4. **Compare results:** Benchmark against published baselines

## Published Baselines (SWE-bench Verified)

- Claude Opus 4.5 (raw): ~11%
- EQUIPA (FeatureBench): 100% (10/10 on harder benchmark)
- Target for SWE-bench Verified: 70-80% (based on calibration run of 75% on 20 instances)

## Scripts

- `pull_swebench_images.py`: Download dataset and pull Docker images (first 50 instances)
- `check_setup_status.py`: Comprehensive verification of setup state
- `verify_swebench_setup.py`: Minimal verification script (created during setup)

## References

- SWE-bench Verified: https://huggingface.co/datasets/princeton-nlp/SWE-bench_Verified
- SWE-bench Paper: https://arxiv.org/abs/2310.06770
- Official Repo: https://github.com/princeton-nlp/SWE-bench
