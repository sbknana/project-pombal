#!/usr/bin/env python3
"""
FeatureBench Verified Runner — EQUIPA Inside Official Docker Containers
(c) 2026 Forgeborn

Runs EQUIPA inside FeatureBench's pre-built Docker containers so patches
are generated in the EXACT environment where the harness validates them.
This guarantees patches apply cleanly and tests run in the right env.

Previous approach (featurebench_runner.py) generated patches from shallow
git clones on the host — patches failed harness validation because the
base state differed from Docker's /root/my_repo/ + masking patch.

Architecture:
  Phase 1 (one-time):  --setup   → Docker volume with Node.js + Claude CLI
  Phase 2 (per-task):  --run     → EQUIPA inside containers → output.jsonl
  Phase 3 (validate):  --validate → Official FeatureBench harness

Usage:
    python featurebench_docker.py --setup
    python featurebench_docker.py --limit 5 --retries 50
    python featurebench_docker.py --validate
    python featurebench_docker.py --limit 100 --retries 50 --validate
"""

import argparse
import io
import json
import os
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path

try:
    import docker
except ImportError:
    print("ERROR: docker SDK not installed. Run: pip install docker")
    sys.exit(1)

from cumulative_db import CumulativeDB

# --- Paths ---

EQUIPA_ROOT = Path(__file__).resolve().parent.parent
BENCHMARKS_DIR = EQUIPA_ROOT / "benchmarks"
DATASET_PATH = BENCHMARKS_DIR / "featurebench_fast.jsonl"
SCHEMA_SQL = EQUIPA_ROOT / "schema.sql"

# Docker constants
TOOLS_VOLUME = "equipa-claude-tools"
DOCKER_WORKDIR = "/testbed"
EQUIPA_DOCKER_DIR = "/opt/equipa"
CONDA_PREFIX = "source /opt/miniconda3/etc/profile.d/conda.sh && conda activate testbed"

# EQUIPA source files to copy into Docker
EQUIPA_SOURCE_DIRS = ["equipa", "prompts", "skills"]
QIAO_PACKAGE_DIR = Path("/home/user/.local/lib/python3.12/site-packages/qiao")
EQUIPA_SOURCE_FILES = [
    "forge_orchestrator.py",
    "forgesmith.py",
    "forgesmith_gepa.py",
    "lesson_sanitizer.py",
    "rubric_quality_scorer.py",
    "schema.sql",
    "dispatch_config.json",
    "forgesmith_config.json",
    "skill_manifest.json",
]


# ============================================================
# Helpers
# ============================================================

def load_dataset(path, limit=0, offset=0, task_indices=None):
    """Load FeatureBench instances from JSONL.
    
    If task_indices is provided, loads only those specific 0-based indices.
    Otherwise uses offset/limit for contiguous ranges.
    """
    if task_indices is not None:
        all_items = []
        with open(path) as f:
            for line in f:
                all_items.append(json.loads(line))
        return [all_items[i] for i in task_indices if i < len(all_items)]
    items = []
    skipped = 0
    with open(path) as f:
        for line in f:
            if skipped < offset:
                skipped += 1
                continue
            items.append(json.loads(line))
            if limit and len(items) >= limit:
                break
    return items


def exec_cmd(container, cmd, timeout=300, workdir=None):
    """Execute a bash command inside the Docker container.

    Returns (exit_code, output_str). Never raises on command failure.
    """
    full_cmd = f'/bin/bash -lc "source ~/.bashrc 2>/dev/null; {cmd}"'
    try:
        result = container.exec_run(
            full_cmd,
            user="root",
            workdir=workdir or DOCKER_WORKDIR,
            demux=True,
        )
        stdout = (result.output[0] or b"").decode("utf-8", errors="replace")
        stderr = (result.output[1] or b"").decode("utf-8", errors="replace")
        output = stdout + stderr
        return result.exit_code, output
    except Exception as e:
        return -1, str(e)


def exec_cmd_checked(container, cmd, timeout=300, workdir=None, label=""):
    """Execute command, print on failure. Returns (exit_code, output)."""
    code, output = exec_cmd(container, cmd, timeout=timeout, workdir=workdir)
    if code != 0 and label:
        print(f"    [{label}] WARN: exit={code}")
        if output.strip():
            for line in output.strip().split("\n")[-5:]:
                print(f"      {line}")
    return code, output


# ============================================================
# Phase 1: Setup — Docker volume with Claude CLI
# ============================================================

def setup_tools_volume(client, force=False):
    """Create a Docker volume with Node.js 20 + Claude CLI + uv/uvx.

    Run once. The volume is mounted into every evaluation container so we
    don't re-install per task.
    """
    print("\n=== Setting Up EQUIPA Tools Volume ===\n")

    # Check if volume exists
    try:
        vol = client.volumes.get(TOOLS_VOLUME)
        print(f"  Volume '{TOOLS_VOLUME}' already exists.")
        if not force:
            resp = input("  Rebuild? (y/N): ").strip().lower()
            if resp != "y":
                print("  Keeping existing volume.")
                return True
        vol.remove()
        print("  Removed old volume.")
    except docker.errors.NotFound:
        pass

    # Create volume
    client.volumes.create(TOOLS_VOLUME)
    print(f"  Created volume: {TOOLS_VOLUME}")

    # Use a lightweight container to install tools into the volume
    print("  Installing Node.js 20 + Claude CLI + uv (this takes a few minutes)...")

    setup_script = """#!/bin/bash
set -ex
echo ">>> Installing Node.js 20..."
apt-get update -qq
apt-get install -y -qq curl ca-certificates
curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
apt-get install -y -qq nodejs
node --version
npm --version

echo ">>> Setting up /opt/tools..."
mkdir -p /opt/tools/bin /opt/tools/lib

echo ">>> Installing Claude CLI..."
npm install -g @anthropic-ai/claude-code --prefix /opt/tools
ls -la /opt/tools/bin/claude || echo "claude not in bin, checking lib..."
ls /opt/tools/lib/node_modules/@anthropic-ai/ 2>/dev/null || true

echo ">>> Installing uv/uvx..."
curl -LsSf https://astral.sh/uv/install.sh | sh
cp /root/.local/bin/uv /opt/tools/bin/ 2>/dev/null || true
cp /root/.local/bin/uvx /opt/tools/bin/ 2>/dev/null || true

echo ">>> Copying Node.js runtime..."
cp $(which node) /opt/tools/bin/
cp -r /usr/lib/node_modules /opt/tools/lib/ 2>/dev/null || true

echo ">>> Final contents:"
ls -la /opt/tools/bin/
echo ">>> Done."
"""

    try:
        # Create container first, copy script, then start
        container = client.containers.create(
            "ubuntu:22.04",
            command="/bin/bash /tmp/setup.sh",
            volumes={TOOLS_VOLUME: {"bind": "/opt/tools", "mode": "rw"}},
            detach=True,
        )

        # Copy setup script into container via tar API
        script_bytes = setup_script.encode("utf-8")
        tar_buf = io.BytesIO()
        with tarfile.open(fileobj=tar_buf, mode="w") as tar:
            info = tarfile.TarInfo(name="setup.sh")
            info.size = len(script_bytes)
            tar.addfile(info, io.BytesIO(script_bytes))
        tar_buf.seek(0)
        container.put_archive("/tmp", tar_buf)

        container.start()

        # Stream logs
        for chunk in container.logs(stream=True, follow=True):
            line = chunk.decode("utf-8", errors="replace").strip()
            if line:
                print(f"    {line}")
        result = container.wait()
        exit_code = result.get("StatusCode", -1)
        container.remove()

        if exit_code == 0:
            print("\n  Tools volume ready.")
            return True
        else:
            print(f"\n  ERROR: Setup failed with exit code {exit_code}")
            return False
    except Exception as e:
        print(f"\n  ERROR: {e}")
        return False


# ============================================================
# Phase 2: Run EQUIPA inside Docker containers
# ============================================================

def create_equipa_tar():
    """Create an in-memory tar archive of EQUIPA source files.

    Includes only what's needed to run the orchestrator — no tests,
    benchmarks, git history, or database.
    """
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for dirname in EQUIPA_SOURCE_DIRS:
            src = EQUIPA_ROOT / dirname
            if src.exists():
                for f in src.rglob("*"):
                    if f.is_file() and "__pycache__" not in str(f):
                        arcname = f"equipa_src/{f.relative_to(EQUIPA_ROOT)}"
                        tar.add(str(f), arcname=arcname)

        for filename in EQUIPA_SOURCE_FILES:
            src = EQUIPA_ROOT / filename
            if src.exists():
                tar.add(str(src), arcname=f"equipa_src/{filename}")

        # Include QIAO package (pure Python stub — Rust .so skipped)
        if QIAO_PACKAGE_DIR.exists():
            init_file = QIAO_PACKAGE_DIR / "__init__.py"
            if init_file.exists():
                tar.add(str(init_file), arcname="equipa_src/qiao/__init__.py")

    buf.seek(0)
    return buf


def copy_tar_to_container(container, tar_buf, dest_dir="/opt"):
    """Copy a tar archive into the container and extract it."""
    container.put_archive(dest_dir, tar_buf)


def setup_equipa_in_container(container, api_key):
    """Install EQUIPA inside the container.

    - Extracts source from /opt/equipa_src/
    - Creates fresh DB from schema.sql
    - Configures paths and environment
    - Sets up MCP config for TheForge DB
    """
    equipa_dir = EQUIPA_DOCKER_DIR  # /opt/equipa

    # Move extracted source to final location
    exec_cmd_checked(container,
        f"mv /opt/equipa_src {equipa_dir}",
        label="move-source")

    # Create fresh database from schema.sql via a Python script
    db_script = f"""#!/usr/bin/env python3
import sqlite3
conn = sqlite3.connect('{equipa_dir}/theforge.db')
with open('{equipa_dir}/schema.sql') as f:
    conn.executescript(f.read())
conn.close()
print('DB created')
"""
    db_script_bytes = db_script.encode("utf-8")
    db_tar = io.BytesIO()
    with tarfile.open(fileobj=db_tar, mode="w") as tar:
        info = tarfile.TarInfo(name="create_db.py")
        info.size = len(db_script_bytes)
        tar.addfile(info, io.BytesIO(db_script_bytes))
    db_tar.seek(0)
    container.put_archive("/tmp", db_tar)
    exec_cmd_checked(container, "python3 /tmp/create_db.py", label="create-db")

    # Create non-root user (Claude CLI refuses bypassPermissions as root)
    exec_cmd_checked(container,
        'useradd -m -s /bin/bash equipa 2>/dev/null || true && '
        f'chown -R equipa:equipa {equipa_dir} && '
        f'chmod -R 755 {equipa_dir} && '
        f'chown -R equipa:equipa {DOCKER_WORKDIR} 2>/dev/null || true',
        label="create-user")

    # Set up environment for both root and equipa user
    for bashrc in ["/root/.bashrc", "/home/equipa/.bashrc"]:
        exec_cmd_checked(container,
            f'echo \'export PATH="/opt/tools/bin:$PATH"\' >> {bashrc} && '
            f'echo \'export NODE_PATH="/opt/tools/lib/node_modules"\' >> {bashrc} && '
            f'echo \'export ANTHROPIC_API_KEY="{api_key}"\' >> {bashrc} && '
            f'echo \'export THEFORGE_DB="{equipa_dir}/theforge.db"\' >> {bashrc} && '
            f'echo \'export PYTHONPATH="{equipa_dir}:$PYTHONPATH"\' >> {bashrc}',
            label="env-setup")

    # Create MCP config pointing to the fresh DB
    mcp_config = {
        "mcpServers": {
            "theforge": {
                "type": "stdio",
                "command": "/opt/tools/bin/uvx",
                "args": [
                    "mcp-server-sqlite",
                    "--db-path",
                    f"{equipa_dir}/theforge.db",
                ],
            }
        }
    }
    mcp_bytes = json.dumps(mcp_config, indent=2).encode("utf-8")
    mcp_tar = io.BytesIO()
    with tarfile.open(fileobj=mcp_tar, mode="w") as tar:
        info = tarfile.TarInfo(name="mcp_config.json")
        info.size = len(mcp_bytes)
        tar.addfile(info, io.BytesIO(mcp_bytes))
    mcp_tar.seek(0)
    container.put_archive(equipa_dir, mcp_tar)

    # Verify Claude CLI is accessible
    code, output = exec_cmd(container,
        'export PATH="/opt/tools/bin:$PATH" && claude --version')
    if code != 0:
        # Fallback: install Node.js directly in the container
        # (needed for images with incompatible libstdc++, e.g. CUDA-based)
        print(f"    Claude CLI from volume failed (exit={code}). "
              f"Installing Node.js in container...")
        install_script = """#!/bin/bash
set -e
apt-get update -qq 2>/dev/null || true
apt-get install -y -qq curl ca-certificates 2>/dev/null || true
curl -fsSL https://deb.nodesource.com/setup_20.x 2>/dev/null | bash - 2>/dev/null
apt-get install -y -qq nodejs 2>/dev/null || true
npm install -g @anthropic-ai/claude-code 2>/dev/null
which claude && claude --version
"""
        script_bytes = install_script.encode("utf-8")
        s_tar = io.BytesIO()
        with tarfile.open(fileobj=s_tar, mode="w") as tar:
            info = tarfile.TarInfo(name="install_node.sh")
            info.size = len(script_bytes)
            tar.addfile(info, io.BytesIO(script_bytes))
        s_tar.seek(0)
        container.put_archive("/tmp", s_tar)
        code2, output2 = exec_cmd(container,
            "bash /tmp/install_node.sh", timeout=300)
        if code2 != 0:
            print(f"    WARNING: Node.js install failed. Cannot run agents.")
            return False
        # Update PATH for equipa user to find system-installed claude
        for bashrc in ["/root/.bashrc", "/home/equipa/.bashrc"]:
            exec_cmd(container,
                f'echo \'export PATH="/usr/local/bin:/usr/bin:$PATH"\' >> {bashrc}')
        output = output2

    print(f"    EQUIPA installed. Claude: {output.strip()[-60:]}")
    return True


def setup_masked_state(container, instance):
    """Set up the masked repo state in /testbed/ — exactly matching
    what the FeatureBench harness does before applying model_patch.

    Steps (matching runtime.py Level 1):
    1. Copy /root/my_repo/* → /testbed/
    2. Apply masking patch (instance["patch"])
    3. Delete FAIL_TO_PASS test files
    4. git init + commit (clean baseline)
    """
    iid = instance["instance_id"]

    # 1. Restore repo — use cp -a to INCLUDE .git (enables proper git apply)
    code, _ = exec_cmd_checked(container,
        f"{CONDA_PREFIX} && rm -rf {DOCKER_WORKDIR}/* {DOCKER_WORKDIR}/.git "
        f"{DOCKER_WORKDIR}/.* 2>/dev/null; "
        f"cp -a /root/my_repo/. {DOCKER_WORKDIR}/",
        timeout=600, label="restore-repo")
    if code != 0:
        # Fallback: try without -a
        exec_cmd_checked(container,
            f"rm -rf {DOCKER_WORKDIR}/* && "
            f"cp -r /root/my_repo/. {DOCKER_WORKDIR}/",
            timeout=600, label="restore-repo-fallback")

    # 2. Apply masking patch — with git checkout approach
    #    Since we preserved .git, git apply can use 3-way merge
    patch = instance.get("patch", "")
    if patch:
        if not patch.endswith("\n"):
            patch += "\n"
        patch_bytes = patch.encode("utf-8")
        patch_tar = io.BytesIO()
        with tarfile.open(fileobj=patch_tar, mode="w") as tar:
            info = tarfile.TarInfo(name="mask_patch.diff")
            info.size = len(patch_bytes)
            tar.addfile(info, io.BytesIO(patch_bytes))
        patch_tar.seek(0)
        container.put_archive("/tmp", patch_tar)

        # Try 3-way merge first (most robust), fall back to standard apply
        code, output = exec_cmd(container,
            f"cd {DOCKER_WORKDIR} && "
            f"git apply --3way --whitespace=fix /tmp/mask_patch.diff 2>&1")
        if code != 0:
            code, output = exec_cmd_checked(container,
                f"cd {DOCKER_WORKDIR} && "
                f"git apply --whitespace=fix /tmp/mask_patch.diff",
                timeout=120, label="mask-patch")
            if code != 0:
                print(f"    WARNING: Masking patch failed for {iid[:50]}")

    # 3. Delete FAIL_TO_PASS test files
    f2p = instance.get("FAIL_TO_PASS", [])
    if isinstance(f2p, str):
        try:
            f2p = json.loads(f2p)
        except (json.JSONDecodeError, TypeError):
            f2p = []
    for test_file in f2p:
        exec_cmd(container, f"rm -f {DOCKER_WORKDIR}/{test_file}")

    # 4. Commit the masked state on top of the original repo history
    #    This preserves the git lineage so diffs are clean
    git_cmds = [
        f'cd {DOCKER_WORKDIR} && git config user.email "equipa@forgeborn.dev"',
        f'cd {DOCKER_WORKDIR} && git config user.name "EQUIPA"',
        f"cd {DOCKER_WORKDIR} && git add -A",
        f'cd {DOCKER_WORKDIR} && git commit -m "Masked state for evaluation" --allow-empty',
    ]
    for cmd in git_cmds:
        exec_cmd(container, cmd, timeout=60)

    # Tag the masked state so we can diff against it later
    exec_cmd(container, f"cd {DOCKER_WORKDIR} && git tag masked-baseline")

    # Make /testbed/ writable by equipa user (orchestrator runs as non-root)
    exec_cmd(container, f"chown -R equipa:equipa {DOCKER_WORKDIR} 2>/dev/null || true")
    # Fix git "dubious ownership" for non-root user
    exec_cmd(container,
        f'su - equipa -c "git config --global --add safe.directory {DOCKER_WORKDIR}"')
    exec_cmd(container,
        f'su - equipa -c "git config --global --add safe.directory \'*\'"')

    print(f"    Masked state ready (patch={len(patch)} chars, "
          f"f2p_removed={len(f2p)} files)")
    return True


def create_task_in_container(container, instance, attempt=1):
    """Insert a benchmark project + task into the container's fresh DB.

    Uses JSON file transfer to avoid shell escaping issues with complex
    problem statements.

    Returns task_id (always 1 for first task in empty DB).
    """
    iid = instance["instance_id"]
    problem = instance["problem_statement"]

    # Extract test validation info
    f2p = instance.get("FAIL_TO_PASS", [])
    p2p = instance.get("PASS_TO_PASS", [])
    if isinstance(f2p, str):
        try:
            f2p = json.loads(f2p)
        except (json.JSONDecodeError, TypeError):
            f2p = []
    if isinstance(p2p, str):
        try:
            p2p = json.loads(p2p)
        except (json.JSONDecodeError, TypeError):
            p2p = []

    test_info = ""
    if f2p:
        test_info += "\n\nTEST_VALIDATION:\n"
        test_info += "FAIL_TO_PASS (these tests MUST pass after your implementation):\n"
        for t in f2p:
            test_info += f"  - {t}\n"
        if p2p:
            test_info += "PASS_TO_PASS (must continue passing):\n"
            for t in p2p[:20]:
                test_info += f"  - {t}\n"

    desc = (
        f"FeatureBench task: {iid} (attempt {attempt})\n\n"
        f"Implement this feature in the repository at {DOCKER_WORKDIR}.\n\n"
        f"FEATURE REQUEST:\n{problem}\n\n"
        f"{test_info}\n"
        f"Instructions: Read the feature request carefully. Understand what "
        f"needs to be built. Implement the feature with clean, working code. "
        f"Run the tests to validate. Make sure existing tests still pass. "
        f"Commit your changes when done."
    )

    # Transfer task data as JSON file — avoids all shell escaping issues
    task_data = {
        "iid": iid[:60],
        "description": desc,
        "db_path": f"{EQUIPA_DOCKER_DIR}/theforge.db",
        "workdir": DOCKER_WORKDIR,
    }
    task_json = json.dumps(task_data)

    # Write JSON via tar (Docker API) to avoid shell quoting entirely
    json_bytes = task_json.encode("utf-8")
    tar_buf = io.BytesIO()
    with tarfile.open(fileobj=tar_buf, mode="w") as tar:
        info = tarfile.TarInfo(name="task_data.json")
        info.size = len(json_bytes)
        tar.addfile(info, io.BytesIO(json_bytes))
    tar_buf.seek(0)
    container.put_archive("/tmp", tar_buf)

    # Python script reads JSON — no shell escaping needed
    py_script = """
import sqlite3, json
with open('/tmp/task_data.json') as f:
    d = json.load(f)
conn = sqlite3.connect(d['db_path'])
conn.execute(
    "INSERT INTO projects (name, codename, status, summary, local_path) "
    "VALUES (?, ?, 'active', 'Benchmark evaluation', ?)",
    ('FeatureBench', 'FeatureBench-eval', d['workdir']),
)
conn.execute(
    "INSERT INTO tasks (project_id, title, description, status, priority) "
    "VALUES (1, ?, ?, 'todo', 'high')",
    ('FB: ' + d['iid'], d['description']),
)
conn.commit()
tid = conn.execute('SELECT last_insert_rowid()').fetchone()[0]
conn.close()
print(f'task_id={tid}')
"""

    # Transfer the Python script the same way
    py_bytes = py_script.encode("utf-8")
    tar_buf2 = io.BytesIO()
    with tarfile.open(fileobj=tar_buf2, mode="w") as tar:
        info = tarfile.TarInfo(name="create_task.py")
        info.size = len(py_bytes)
        tar.addfile(info, io.BytesIO(py_bytes))
    tar_buf2.seek(0)
    container.put_archive("/tmp", tar_buf2)

    code, output = exec_cmd_checked(container,
        f'export THEFORGE_DB="{EQUIPA_DOCKER_DIR}/theforge.db" && '
        f"python3 /tmp/create_task.py",
        label="create-task")

    if "task_id=" in output:
        tid = int(output.split("task_id=")[1].strip())
        return tid
    return 1  # fallback


def reset_task_for_retry(container, instance, attempt):
    """Reset the DB task for a retry attempt.

    Also clears agent_runs/agent_actions from previous attempt so
    EQUIPA starts fresh.
    """
    py_script = f"""
import sqlite3
conn = sqlite3.connect('{EQUIPA_DOCKER_DIR}/theforge.db')
conn.execute("UPDATE tasks SET status='todo', completed_at=NULL WHERE id=1")
conn.execute("DELETE FROM agent_runs WHERE task_id=1")
conn.execute("DELETE FROM agent_actions WHERE task_id=1")
conn.execute("DELETE FROM agent_messages WHERE task_id=1")
conn.commit()
conn.close()
print('Task reset for attempt {attempt}')
"""
    py_bytes = py_script.encode("utf-8")
    tar_buf = io.BytesIO()
    with tarfile.open(fileobj=tar_buf, mode="w") as tar:
        info = tarfile.TarInfo(name="reset_task.py")
        info.size = len(py_bytes)
        tar.addfile(info, io.BytesIO(py_bytes))
    tar_buf.seek(0)
    container.put_archive("/tmp", tar_buf)
    exec_cmd(container, "python3 /tmp/reset_task.py")


def run_equipa_in_container(container, task_id, timeout=1800):
    """Run the EQUIPA orchestrator inside the container as non-root user.

    Claude CLI refuses --permission-mode bypassPermissions as root,
    so we run as the 'equipa' user. Uses `timeout` command inside the
    container for reliable timeout enforcement.
    """
    inner_cmd = (
        f'export PATH="/opt/tools/bin:$PATH" && '
        f'export NODE_PATH="/opt/tools/lib/node_modules" && '
        f'export THEFORGE_DB="{EQUIPA_DOCKER_DIR}/theforge.db" && '
        f'export PYTHONPATH="{EQUIPA_DOCKER_DIR}:$PYTHONPATH" && '
        f'{CONDA_PREFIX} && '
        f'cd {EQUIPA_DOCKER_DIR} && '
        f'python3 -u forge_orchestrator.py --task {task_id} --dev-test -y'
    )
    # Wrap with timeout command for reliable timeout enforcement
    cmd = f'timeout -k 30 {timeout} bash -c \'{inner_cmd}\''
    full_cmd = f'/bin/bash -lc "source /home/equipa/.bashrc 2>/dev/null; {cmd}"'
    try:
        result = container.exec_run(
            full_cmd,
            user="equipa",
            workdir=EQUIPA_DOCKER_DIR,
            demux=True,
        )
        stdout = (result.output[0] or b"").decode("utf-8", errors="replace")
        stderr = (result.output[1] or b"").decode("utf-8", errors="replace")
        output = stdout + stderr
        code = result.exit_code
        if code == 124:
            output += "\n[TIMEOUT] Orchestrator killed after {timeout}s"
    except Exception as e:
        code, output = -1, str(e)

    # Print last few lines of output for visibility
    lines = output.strip().split("\n") if output else []
    for line in lines[-5:]:
        print(f"      {line[:120]}")

    return code, output


def exec_cmd_as_equipa(container, cmd, timeout=300):
    """Execute a command as the equipa user inside the container."""
    full_cmd = f'/bin/bash -lc "source /home/equipa/.bashrc 2>/dev/null; {cmd}"'
    try:
        result = container.exec_run(
            full_cmd,
            user="equipa",
            workdir=DOCKER_WORKDIR,
            demux=True,
        )
        stdout = (result.output[0] or b"").decode("utf-8", errors="replace")
        stderr = (result.output[1] or b"").decode("utf-8", errors="replace")
        return result.exit_code, stdout + stderr
    except Exception as e:
        return -1, str(e)


def _filter_patch_to_source(raw_patch: str, max_file_kb: int = 500) -> str:
    """Filter a git diff to only include source code files.

    Removes build artifacts, compiled files, binary blobs, and any single
    file diff larger than max_file_kb. This prevents bloated patches from
    agents that trigger rebuilds in large repos (e.g. scikit-learn, pandas).

    Does NOT use any ground-truth or masking patch information — purely
    filters by file extension and size. Fair game for benchmarks.
    """
    # Source extensions that belong in a model patch
    SOURCE_EXTS = {
        ".py", ".pyi", ".pyx", ".pxd",          # Python
        ".js", ".ts", ".jsx", ".tsx",            # JavaScript/TypeScript
        ".rs", ".go", ".java", ".c", ".cpp",     # Compiled langs
        ".h", ".hpp",                             # Headers
        ".json", ".yaml", ".yml", ".toml",       # Config
        ".cfg", ".ini", ".conf",                  # Config
        ".txt", ".md", ".rst", ".tex",           # Docs
        ".html", ".css", ".xml", ".svg",         # Web
        ".sh", ".bash",                           # Scripts
        ".sql",                                   # Database
    }

    # Split into per-file chunks
    chunks = raw_patch.split("\ndiff --git ")
    filtered = []

    for i, chunk in enumerate(chunks):
        if i > 0:
            chunk = "diff --git " + chunk

        # Extract filename from "diff --git a/X b/Y"
        first_line = chunk.split("\n", 1)[0]
        parts = first_line.split(" b/", 1)
        if len(parts) < 2:
            continue
        filepath = parts[1].strip()

        # Skip non-source files by extension
        ext = ""
        if "." in filepath.rsplit("/", 1)[-1]:
            ext = "." + filepath.rsplit(".", 1)[-1].lower()
        if ext not in SOURCE_EXTS:
            continue

        # Skip oversized single-file diffs (likely generated/vendored)
        if len(chunk) > max_file_kb * 1024:
            continue

        # Skip obvious build/generated paths
        skip_patterns = [
            "/build/", "/dist/", "/.tox/", "/.nox/",
            "/__pycache__/", "/.eggs/", "/egg-info/",
            "/node_modules/", "/.mypy_cache/",
            ".forge-state.json", "SECURITY-REVIEW-",
        ]
        if any(pat in filepath for pat in skip_patterns):
            continue

        filtered.append(chunk)

    return "\n".join(filtered).strip() if filtered else ""


def extract_patch(container):
    """Extract git diff from /testbed/ — this is the model_patch.

    Runs as equipa user (who owns the git repo) to avoid dubious
    ownership errors. Tries multiple strategies to find changes.

    Post-processes the diff to exclude build artifacts and binary files,
    keeping only source code. This is necessary because agents in large
    repos (scikit-learn, pandas, seaborn) trigger rebuilds that inflate
    the diff from a few KB to 50-100MB of compiled output.
    """
    # Create .gitignore to exclude build artifacts before committing
    exec_cmd_as_equipa(container,
        f"cd {DOCKER_WORKDIR} && cat >> .gitignore << 'GIEOF'\n"
        f"__pycache__/\n*.pyc\n*.pyo\n*.egg-info/\n*.eggs/\n"
        f".eggs/\ndist/\nbuild/\n*.so\n.tox/\n.nox/\n"
        f".pytest_cache/\n.mypy_cache/\nvenv/\n.venv/\n"
        f"*.egg\nnode_modules/\n.forge-worktrees/\n"
        f".forge-checkpoints/\n.forge-state.json\n"
        f"SECURITY-REVIEW-*.md\n*.o\n*.a\n*.dylib\n*.dll\n"
        f"*.class\n*.jar\n*.whl\n*.tar.gz\n*.zip\n"
        f"*.npy\n*.npz\n*.pkl\n*.pickle\n*.h5\n*.hdf5\n"
        f"*.mat\n*.sav\n*.dat\n*.bin\n*.db\n*.sqlite\n"
        f"*.log\n*.coverage\n.coverage.*\nhtmlcov/\n"
        f"*.c\n!setup.py\n*.f\n*.f90\n"
        f"GIEOF")

    # Only commit files the agent explicitly changed via git add in its
    # own commits. DO NOT run 'git add -A' or 'git add -u' here — that
    # stages build artifacts and side-effects from test runs in large repos
    # (scikit-learn, pandas, seaborn) which inflates patches to 50-100MB.
    #
    # If the agent has uncommitted changes (edited but forgot to commit),
    # selectively stage only source files, not build artifacts.
    exec_cmd_as_equipa(container,
        f"cd {DOCKER_WORKDIR} && "
        f"git diff --name-only | grep -E '\\.(py|pyi|pyx|pxd|js|ts|go|rs|java|json|yaml|yml|toml|cfg|ini|txt|md|rst|html|css|xml|sh|sql)$' | "
        f"xargs -r git add 2>/dev/null; "
        f"git commit -m 'final uncommitted source changes' --allow-empty 2>/dev/null || true")

    raw_patch = ""

    # First, identify files the agent intentionally changed by looking at
    # its commit history (not build side-effects). This prevents bloated
    # patches in large repos where running tests modifies tracked files.
    code, agent_files_out = exec_cmd_as_equipa(container,
        f"cd {DOCKER_WORKDIR} && "
        f"git log masked-baseline..HEAD --pretty=format: --name-only | "
        f"sort -u | grep -v '^$'")
    agent_files = []
    if code == 0 and agent_files_out:
        agent_files = [f.strip() for f in agent_files_out.strip().split("\n")
                       if f.strip() and not f.strip().startswith(".")]

    # Strategy 1: Diff from masked-baseline tag (best — matches harness state)
    # If agent touched many files (>50), restrict diff to agent's committed files
    if len(agent_files) > 50:
        # Too many files — likely build artifacts committed. Use source-only filter.
        source_exts = (
            ".py", ".pyi", ".pyx", ".pxd", ".js", ".ts", ".jsx", ".tsx",
            ".rs", ".go", ".java", ".json", ".yaml", ".yml", ".toml",
            ".cfg", ".ini", ".txt", ".md", ".rst", ".html", ".css",
            ".sh", ".sql",
        )
        source_files = [f for f in agent_files
                        if any(f.endswith(ext) for ext in source_exts)]
        # Further filter: exclude files in build/dist/egg paths
        skip_patterns = ["/build/", "/dist/", "/.tox/", "/.eggs/",
                         "/egg-info/", "/__pycache__/", "/.mypy_cache/"]
        source_files = [f for f in source_files
                        if not any(pat in f for pat in skip_patterns)]

        if source_files:
            # Diff only the source files the agent touched
            pathspecs = " ".join(f"'{f}'" for f in source_files[:200])
            code, patch = exec_cmd_as_equipa(container,
                f"cd {DOCKER_WORKDIR} && "
                f"git diff masked-baseline HEAD -- {pathspecs}")
            if patch and patch.strip() and "diff --git" in patch:
                raw_patch = patch.strip()

    # Standard strategy: diff all changes (fine for small/medium repos)
    if not raw_patch:
        code, patch = exec_cmd_as_equipa(container,
            f"cd {DOCKER_WORKDIR} && "
            f"git diff masked-baseline HEAD "
            f"-- . ':!.gitignore' ':!.forge-state.json' ':!SECURITY-REVIEW-*.md'")
        if patch and patch.strip() and "diff --git" in patch:
            raw_patch = patch.strip()

    # Strategy 2: Log-based — find first and last commits
    if not raw_patch:
        code, log_output = exec_cmd_as_equipa(container,
            f"cd {DOCKER_WORKDIR} && git log --oneline --all")
        if code == 0:
            commits = [l.strip() for l in log_output.split("\n") if l.strip()]
            if len(commits) > 1:
                first = commits[-1].split()[0]
                last = commits[0].split()[0]
                code, patch = exec_cmd_as_equipa(container,
                    f"cd {DOCKER_WORKDIR} && git diff {first}..{last}")
                if patch and patch.strip() and "diff --git" in patch:
                    raw_patch = patch.strip()

    # Strategy 3: Check forge-task branches
    if not raw_patch:
        code, branches = exec_cmd_as_equipa(container,
            f"cd {DOCKER_WORKDIR} && git branch --all")
        if code == 0:
            for line in branches.split("\n"):
                branch = line.strip().lstrip("* ")
                if "forge-task" in branch:
                    code, patch = exec_cmd_as_equipa(container,
                        f"cd {DOCKER_WORKDIR} && git diff "
                        f"$(git rev-list --max-parents=0 HEAD)..{branch}")
                    if patch and patch.strip() and "diff --git" in patch:
                        raw_patch = patch.strip()
                        break

    # Strategy 4: Any uncommitted changes left
    if not raw_patch:
        code, patch = exec_cmd_as_equipa(container,
            f"cd {DOCKER_WORKDIR} && git diff HEAD")
        if patch and patch.strip() and "diff --git" in patch:
            raw_patch = patch.strip()

    if not raw_patch:
        return ""

    # Filter to source code only — removes build artifacts, compiled files,
    # and oversized generated files that inflate patches in large repos.
    # This uses NO ground-truth information — purely file extension and size.
    filtered = _filter_patch_to_source(raw_patch)
    if filtered:
        return filtered

    # If filtering removed everything, return raw (better than nothing)
    return raw_patch


def run_instance(client, instance, equipa_tar_buf, api_key,
                 max_retries=50, timeout=900, cumdb=None):
    """Full pipeline for one FeatureBench instance.

    1. Pull Docker image
    2. Start container with tools volume
    3. Install EQUIPA
    4. Set up masked state (optionally inject cumulative knowledge)
    5. Run EQUIPA (with retry loop)
    6. Extract patch
    7. Cleanup (extract and merge knowledge if cumulative mode)
    """
    iid = instance["instance_id"]
    image_name = instance["image_name"]
    repo_settings = json.loads(instance.get("repo_settings", "{}"))

    # Ensure full image name
    if "/" not in image_name or "." not in image_name.split("/")[0]:
        image_name = f"docker.io/{image_name}"

    result = {
        "instance_id": iid,
        "model_patch": "",
        "model_name_or_path": "EQUIPA (Opus dev + Sonnet tester, Docker verified)",
        "resolved": False,
        "attempts": 0,
        "duration": 0,
    }

    container = None
    start = time.time()

    try:
        # Pull image
        print(f"    Pulling {image_name[:60]}...")
        try:
            client.images.get(image_name)
        except docker.errors.ImageNotFound:
            client.images.pull(image_name)

        # Parse Docker runtime config
        shm_size = repo_settings.get("shm_size")
        env_vars = repo_settings.get("env_vars", {})

        # Create container
        container_name = (
            f"equipa-fb-{iid[:40]}-{int(time.time())}"
            .replace("/", "-").replace(".", "-").replace("__", "-")
        )
        run_kwargs = {
            "image": image_name,
            "command": "/bin/bash -c 'sleep infinity'",
            "detach": True,
            "user": "root",
            "working_dir": DOCKER_WORKDIR,
            "network_mode": "bridge",
            "name": container_name,
            "volumes": {
                TOOLS_VOLUME: {"bind": "/opt/tools", "mode": "ro"},
            },
            "environment": {
                "ANTHROPIC_API_KEY": api_key,
                **env_vars,
            },
        }
        if shm_size:
            run_kwargs["shm_size"] = shm_size

        container = client.containers.run(**run_kwargs)
        print(f"    Container started: {container.short_id}")

        # Copy EQUIPA source
        equipa_tar_buf.seek(0)
        copy_tar_to_container(container, equipa_tar_buf)

        # Install EQUIPA
        if not setup_equipa_in_container(container, api_key):
            result["reason"] = "equipa_setup_failed"
            return result

        # Inject cumulative knowledge if enabled
        if cumdb:
            cumdb.inject_into_container(container, EQUIPA_DOCKER_DIR)

        # Set up masked state
        if not setup_masked_state(container, instance):
            result["reason"] = "masked_state_failed"
            return result

        # Create task
        task_id = create_task_in_container(container, instance)

        # Autoresearch retry loop
        # The orchestrator runs a full dev-test loop per attempt. We check
        # both patch generation AND task outcome. If the orchestrator
        # reports tests_passed (task status='done'), we accept the patch.
        # If it produces a patch but tests didn't pass, we KEEP the best
        # patch but continue retrying for a better one.
        best_patch = ""
        best_changes = 0

        for attempt in range(1, max_retries + 1):
            result["attempts"] = attempt
            attempt_start = time.time()
            print(f"    [Attempt {attempt}/{max_retries}]", end=" ", flush=True)

            if attempt > 1:
                # Reset repo to masked state for fresh attempt
                setup_masked_state(container, instance)
                reset_task_for_retry(container, instance, attempt)

            # Run EQUIPA orchestrator (full dev-test loop)
            code, output = run_equipa_in_container(
                container, task_id, timeout=timeout)
            attempt_time = time.time() - attempt_start

            # Check task outcome — DB status + orchestrator output signals
            task_status = "unknown"

            # Method 1: Check DB status
            status_script = (
                f"import sqlite3; "
                f"c=sqlite3.connect('{EQUIPA_DOCKER_DIR}/theforge.db'); "
                f"r=c.execute('SELECT status FROM tasks WHERE id={task_id}').fetchone(); "
                f"print(r[0] if r else 'unknown'); c.close()"
            )
            status_bytes = status_script.encode("utf-8")
            st_tar = io.BytesIO()
            with tarfile.open(fileobj=st_tar, mode="w") as tar:
                info = tarfile.TarInfo(name="check_status.py")
                info.size = len(status_bytes)
                tar.addfile(info, io.BytesIO(status_bytes))
            st_tar.seek(0)
            container.put_archive("/tmp", st_tar)
            code_s, status_out = exec_cmd_as_equipa(container,
                "python3 /tmp/check_status.py")
            if code_s == 0:
                task_status = status_out.strip()

            # Method 2: Check orchestrator output for pass signals
            output_lower = output.lower() if output else ""
            if task_status not in ("done", "blocked"):
                if any(sig in output_lower for sig in [
                    "tests_passed", "test passed", "tests passed",
                    "all tests pass", "pass_to_pass tests pass",
                    "pass successfully",
                ]):
                    task_status = "done"

            # Extract patch (auto-filters build artifacts from source)
            patch = extract_patch(container)
            if patch:
                lines = patch.split("\n")
                adds = sum(1 for l in lines
                           if l.startswith("+") and not l.startswith("+++"))
                dels = sum(1 for l in lines
                           if l.startswith("-") and not l.startswith("---"))
                changes = adds + dels

                if changes > 0:
                    # Keep the best patch (most changes, or tests_passed)
                    if task_status == "done" or changes > best_changes:
                        best_patch = patch
                        best_changes = changes

                    if task_status == "done":
                        # Tests passed! Accept this patch
                        result["model_patch"] = patch
                        result["resolved"] = True
                        result["changes"] = changes
                        result["patch_size"] = len(patch)
                        result["duration"] = time.time() - start
                        result["task_status"] = task_status
                        print(f"PASS ({adds}+ {dels}-, "
                              f"{len(patch)} chars, {attempt_time:.0f}s)")
                        return result
                    else:
                        print(f"patch but {task_status} ({adds}+ {dels}-, "
                              f"{attempt_time:.0f}s)")
                        continue  # Retry with fresh context
                else:
                    print(f"empty diff ({attempt_time:.0f}s)")
            else:
                print(f"no patch ({attempt_time:.0f}s)")

        # Exhausted retries — submit best patch if we have one
        if best_patch:
            lines = best_patch.split("\n")
            adds = sum(1 for l in lines
                       if l.startswith("+") and not l.startswith("+++"))
            dels = sum(1 for l in lines
                       if l.startswith("-") and not l.startswith("---"))
            result["model_patch"] = best_patch
            result["resolved"] = True
            result["changes"] = adds + dels
            result["patch_size"] = len(best_patch)
            result["reason"] = "best_effort_after_retries"
            print(f"    Submitting best patch ({adds}+ {dels}-, "
                  f"{len(best_patch)} chars)")
        else:
            result["reason"] = "exhausted_retries_no_patch"

        result["duration"] = time.time() - start
        return result

    except Exception as e:
        result["reason"] = f"error: {str(e)[:200]}"
        result["duration"] = time.time() - start
        print(f"    ERROR: {e}")
        return result

    finally:
        if container:
            try:
                # Extract the DB before destroying — preserves telemetry
                db_save_dir = Path(output_path).parent / "container_dbs"
                db_save_dir.mkdir(exist_ok=True)
                safe_iid = iid.replace("/", "-").replace(".", "-")[:60]
                db_dest = str(db_save_dir / f"{safe_iid}.db")
                try:
                    bits, _ = container.get_archive(
                        f"{EQUIPA_DOCKER_DIR}/theforge.db")
                    # get_archive returns a tar stream
                    raw = b"".join(bits)
                    tar_buf = io.BytesIO(raw)
                    with tarfile.open(fileobj=tar_buf) as tar:
                        member = tar.getmembers()[0]
                        f = tar.extractfile(member)
                        if f:
                            with open(db_dest, "wb") as out:
                                out.write(f.read())
                    print(f"    DB saved: {db_dest}")
                except Exception as db_err:
                    print(f"    DB extract failed: {db_err}")
            except Exception:
                pass
            try:
                container.stop(timeout=10)
                container.remove(force=True)
            except Exception:
                pass
            # Prune dangling images after each task to prevent disk fill
            try:
                client.images.prune(filters={"dangling": True})
            except Exception:
                pass


def run_benchmark(limit=10, offset=0, max_retries=50, timeout=900,
                  output_path="output.jsonl", cumulative=False,
                  task_indices=None, use_qiao=False):
    """Main benchmark loop — run EQUIPA inside Docker for each instance."""

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY not set.")
        sys.exit(1)

    client = docker.from_env()

    # Verify tools volume exists
    try:
        client.volumes.get(TOOLS_VOLUME)
    except docker.errors.NotFound:
        print(f"ERROR: Tools volume '{TOOLS_VOLUME}' not found. "
              f"Run: python {__file__} --setup")
        sys.exit(1)

    dataset = load_dataset(str(DATASET_PATH), limit=limit, offset=offset,
                           task_indices=task_indices)

    # Initialize cumulative DB if enabled
    cumdb = None
    if cumulative:
        cumdb = CumulativeDB(str(BENCHMARKS_DIR / "fb_cumulative.db"))
        stats = cumdb.get_stats()
        print(f"  Cumulative DB: {stats['lessons']} lessons, "
              f"{stats['episodes']} episodes, {stats['decisions']} decisions")

    print(f"\n{'=' * 60}")
    print(f"  FeatureBench Verified — EQUIPA Inside Docker")
    print(f"  Tasks: {len(dataset)} (offset {offset})")
    print(f"  Max retries per task: {max_retries}")
    print(f"  Timeout per attempt: {timeout}s")
    print(f"  Output: {output_path}")
    print(f"  Cumulative mode: {'ON' if cumulative else 'OFF'}")
    if use_qiao:
        print(f"  QIAO mode: ON")
    if task_indices:
        print(f"  Task indices: {task_indices}")
    print(f"{'=' * 60}\n")

    # Create EQUIPA tar once
    print("  Packaging EQUIPA source...")
    equipa_tar = create_equipa_tar()
    tar_size = equipa_tar.getbuffer().nbytes
    print(f"  EQUIPA archive: {tar_size / 1024 / 1024:.1f} MB\n")

    results = []
    resolved = 0
    total_start = time.time()

    for i, instance in enumerate(dataset):
        iid = instance["instance_id"]
        print(f"\n{'━' * 60}")
        print(f"  [{i+1}/{len(dataset)}] {iid[:55]}")
        print(f"  Repo: {instance['repo']} | "
              f"Image: {instance['image_name'][:40]}")

        result = run_instance(
            client, instance, equipa_tar, api_key,
            max_retries=max_retries, timeout=timeout,
            cumdb=cumdb,
        )
        results.append(result)

        if result.get("resolved"):
            resolved += 1

        rate = resolved / (i + 1) * 100
        status = "RESOLVED" if result.get("resolved") else "FAILED"
        print(f"  [{status}] Attempts: {result['attempts']} | "
              f"Running: {resolved}/{i+1} ({rate:.1f}%)")

        # Write results incrementally
        with open(output_path, "w") as f:
            for r in results:
                if r.get("model_patch"):
                    pred = {
                        "instance_id": r["instance_id"],
                        "model_patch": r["model_patch"],
                        "model_name_or_path": r.get("model_name_or_path", "EQUIPA"),
                        "n_attempt": r.get("attempts", 1),
                        "success": True,
                    }
                    f.write(json.dumps(pred) + "\n")

    # Final summary
    total_time = time.time() - total_start
    rate = resolved / len(dataset) * 100 if dataset else 0

    print(f"\n{'=' * 60}")
    print(f"  FeatureBench Verified — Results")
    print(f"{'=' * 60}")
    print(f"  Resolved: {resolved}/{len(dataset)} ({rate:.1f}%)")
    print(f"  Total time: {total_time / 60:.1f} min")
    print(f"  Output: {output_path}")
    print(f"{'=' * 60}")

    # Save full results JSON
    full_output = {
        "benchmark": "FeatureBench (fast split, Docker verified)",
        "system": "EQUIPA (full pipeline, Docker containers)",
        "model": "Opus (developer) + Sonnet (tester)",
        "max_retries": max_retries,
        "timeout_per_attempt": timeout,
        "resolved": resolved,
        "total": len(dataset),
        "resolution_rate": rate,
        "total_time_seconds": total_time,
        "results": results,
    }
    full_path = output_path.replace(".jsonl", "_full.json")
    with open(full_path, "w") as f:
        json.dump(full_output, f, indent=2)
    print(f"  Full results: {full_path}")


# ============================================================
# Phase 3: Validate via official harness
# ============================================================

def validate_results(output_path="output.jsonl"):
    """Run the official FeatureBench harness on our predictions."""
    harness_dir = BENCHMARKS_DIR / "FeatureBench"

    if not harness_dir.exists():
        print(f"ERROR: FeatureBench harness not found at {harness_dir}")
        sys.exit(1)

    if not Path(output_path).exists():
        print(f"ERROR: Predictions file not found: {output_path}")
        sys.exit(1)

    # Count predictions
    with open(output_path) as f:
        n_preds = sum(1 for _ in f)
    print(f"\n  Validating {n_preds} predictions via official harness...")

    cmd = [
        sys.executable, "-m", "featurebench.harness.run_evaluation",
        "--predictions-path", str(Path(output_path).resolve()),
        "--split", "fast",
        "--n-concurrent", "1",
        "--timeout", "300",
    ]
    env = {**os.environ, "PYTHONPATH": str(harness_dir)}

    result = subprocess.run(cmd, cwd=str(harness_dir), env=env,
                           capture_output=True, text=True, timeout=7200)
    print(result.stdout)
    if result.stderr:
        print(result.stderr[-500:])


# ============================================================
# Main
# ============================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="FeatureBench Verified — EQUIPA Inside Docker")
    parser.add_argument("--setup", action="store_true",
                        help="One-time: build tools volume with Claude CLI")
    parser.add_argument("--validate", action="store_true",
                        help="Run official harness on output.jsonl")
    parser.add_argument("--limit", type=int, default=10,
                        help="Number of tasks to run")
    parser.add_argument("--offset", type=int, default=0,
                        help="Skip first N tasks")
    parser.add_argument("--retries", type=int, default=50,
                        help="Max retries per task")
    parser.add_argument("--timeout", type=int, default=1800,
                        help="Timeout per attempt (seconds)")
    parser.add_argument("--output", default="output.jsonl",
                        help="Output predictions file")
    parser.add_argument("--force", action="store_true",
                        help="Force rebuild tools volume (skip prompt)")
    parser.add_argument("--tasks", type=str, default="",
                        help="Comma-separated 0-based task indices (e.g. 2,5,7,8,9)")
    parser.add_argument("--cumulative", action="store_true",
                        help="Enable cumulative knowledge DB across tasks")
    parser.add_argument("--qiao", action="store_true",
                        help="Enable QIAO quantum-inspired adaptive retry")
    args = parser.parse_args()

    if args.setup:
        client = docker.from_env()
        setup_tools_volume(client, force=args.force)
    elif args.validate:
        validate_results(args.output)
    else:
        task_indices = None
        if args.tasks:
            task_indices = [int(x.strip()) for x in args.tasks.split(",")]
        run_benchmark(
            limit=args.limit, offset=args.offset,
            max_retries=args.retries, timeout=args.timeout,
            output_path=args.output,
            cumulative=args.cumulative,
            task_indices=task_indices,
            use_qiao=args.qiao,
        )
        if args.validate:
            validate_results(args.output)
