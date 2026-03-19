#!/usr/bin/env python3
"""SparkForge AI Estimator Research — Weekly Feedback Analysis

Analyzes SparkForge AI quote generator feedback data to identify patterns
and generate insights for prompt improvement.

What it does:
1. Queries ai_analysis_sessions + ai_suggestion_items from SparkForge DB
   (via SSH to apocrypha-vm)
2. Analyzes patterns:
   - Most rejected items by job type
   - Most modified quantities (over/under-estimating)
   - Labor hour accuracy (AI vs actual)
   - Confidence calibration (do high-confidence items get accepted more?)
   - Categories with lowest acceptance rates
3. Generates a markdown findings report
4. Stores findings in TheForge research table
5. If acceptance rate drops below 70% for any job type, flags for prompt review

Schedule (cron on Claudinator):
    0 3 * * 0 cd /path/to/equipa && python3 sparkforge_estimator_research.py

Usage:
    python3 sparkforge_estimator_research.py              # Run analysis, save report
    python3 sparkforge_estimator_research.py --print      # Also print to stdout
    python3 sparkforge_estimator_research.py --db /path   # Custom TheForge DB
    python3 sparkforge_estimator_research.py --dry-run    # Skip DB inserts

Stdlib only — no pip dependencies required.

Copyright 2026 Forgeborn
"""

import json
import os
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SPARKFORGE_SSH_HOST = "apocrypha-vm"
SPARKFORGE_DB_NAME = "sparkforge"
SPARKFORGE_PROJECT_ID = 48
ACCEPTANCE_THRESHOLD = 0.70  # Flag job types below this
REPORT_DIR_NAME = "research"
REPORT_PREFIX = "estimator-analysis"

# SQL queries to run on SparkForge PostgreSQL via SSH + psql
# Each query returns JSON rows for easy parsing

QUERY_SESSIONS_SUMMARY = """
SELECT
    s.job_type,
    COUNT(*) AS total_sessions,
    ROUND(AVG(s.accepted_count::numeric / NULLIF(s.total_suggestions, 0)), 3) AS avg_accept_rate,
    ROUND(AVG(s.avg_confidence), 3) AS avg_confidence,
    ROUND(AVG(s.rejected_count::numeric / NULLIF(s.total_suggestions, 0)), 3) AS avg_reject_rate,
    ROUND(AVG(s.modified_count::numeric / NULLIF(s.total_suggestions, 0)), 3) AS avg_modify_rate,
    SUM(s.total_suggestions) AS total_items,
    SUM(s.accepted_count) AS total_accepted,
    SUM(s.rejected_count) AS total_rejected,
    SUM(s.modified_count) AS total_modified
FROM ai_analysis_sessions s
GROUP BY s.job_type
ORDER BY total_sessions DESC;
"""

QUERY_REJECTED_ITEMS = """
SELECT
    s.job_type,
    i.description,
    i.category,
    COUNT(*) AS times_rejected,
    ROUND(AVG(i.confidence), 3) AS avg_confidence_when_rejected
FROM ai_suggestion_items i
JOIN ai_analysis_sessions s ON i.session_id = s.id
WHERE i.user_action = 'rejected'
GROUP BY s.job_type, i.description, i.category
ORDER BY times_rejected DESC
LIMIT 30;
"""

QUERY_QUANTITY_MODIFICATIONS = """
SELECT
    s.job_type,
    i.description,
    i.category,
    ROUND(AVG(i.quantity), 2) AS avg_ai_qty,
    ROUND(AVG(i.final_quantity), 2) AS avg_final_qty,
    ROUND(AVG(i.final_quantity - i.quantity), 2) AS avg_adjustment,
    ROUND(AVG(
        CASE WHEN i.quantity > 0
        THEN ((i.final_quantity - i.quantity) / i.quantity) * 100
        ELSE 0 END
    ), 1) AS avg_pct_change,
    COUNT(*) AS times_modified
FROM ai_suggestion_items i
JOIN ai_analysis_sessions s ON i.session_id = s.id
WHERE i.user_action = 'modified'
  AND i.final_quantity IS NOT NULL
GROUP BY s.job_type, i.description, i.category
HAVING COUNT(*) >= 2
ORDER BY ABS(AVG(i.final_quantity - i.quantity)) DESC
LIMIT 30;
"""

QUERY_CONFIDENCE_CALIBRATION = """
SELECT
    CASE
        WHEN i.confidence >= 0.90 THEN '90-100%'
        WHEN i.confidence >= 0.80 THEN '80-89%'
        WHEN i.confidence >= 0.70 THEN '70-79%'
        WHEN i.confidence >= 0.60 THEN '60-69%'
        ELSE 'Below 60%'
    END AS confidence_band,
    COUNT(*) AS total_items,
    SUM(CASE WHEN i.user_action = 'accepted' THEN 1 ELSE 0 END) AS accepted,
    SUM(CASE WHEN i.user_action = 'modified' THEN 1 ELSE 0 END) AS modified,
    SUM(CASE WHEN i.user_action = 'rejected' THEN 1 ELSE 0 END) AS rejected,
    ROUND(
        SUM(CASE WHEN i.user_action = 'accepted' THEN 1 ELSE 0 END)::numeric
        / NULLIF(COUNT(*), 0), 3
    ) AS actual_accept_rate
FROM ai_suggestion_items i
GROUP BY confidence_band
ORDER BY confidence_band DESC;
"""

QUERY_CATEGORY_ACCEPTANCE = """
SELECT
    i.category,
    COUNT(*) AS total_items,
    SUM(CASE WHEN i.user_action = 'accepted' THEN 1 ELSE 0 END) AS accepted,
    SUM(CASE WHEN i.user_action = 'modified' THEN 1 ELSE 0 END) AS modified,
    SUM(CASE WHEN i.user_action = 'rejected' THEN 1 ELSE 0 END) AS rejected,
    ROUND(
        SUM(CASE WHEN i.user_action = 'accepted' THEN 1 ELSE 0 END)::numeric
        / NULLIF(COUNT(*), 0), 3
    ) AS accept_rate
FROM ai_suggestion_items i
GROUP BY i.category
ORDER BY accept_rate ASC;
"""

QUERY_OUTCOME_ACCURACY = """
SELECT
    s.job_type,
    s.outcome_status,
    COUNT(*) AS session_count,
    ROUND(AVG(s.accuracy_score), 3) AS avg_accuracy
FROM ai_analysis_sessions s
WHERE s.outcome_status IS NOT NULL
GROUP BY s.job_type, s.outcome_status
ORDER BY s.job_type, s.outcome_status;
"""


# ---------------------------------------------------------------------------
# Database helpers (TheForge — local SQLite)
# ---------------------------------------------------------------------------

def find_db(explicit_path=None):
    """Find theforge.db — explicit path, env var, or scan common locations."""
    if explicit_path:
        return explicit_path

    if os.environ.get("THEFORGE_DB"):
        return os.environ["THEFORGE_DB"]

    for candidate in [
        Path.cwd() / "theforge.db",
        Path.cwd().parent / "theforge.db",
        Path(__file__).resolve().parent / "theforge.db",
    ]:
        if candidate.exists():
            return str(candidate)

    print("ERROR: Cannot find theforge.db")
    print("  Set THEFORGE_DB env var or pass --db /path/to/theforge.db")
    sys.exit(1)


def get_db(db_path):
    """Open a SQLite connection with row factory."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_research_table(conn):
    """Create the research findings table if it doesn't exist."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS research_findings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            report_type TEXT NOT NULL,
            report_date TEXT NOT NULL,
            summary TEXT NOT NULL,
            findings_json TEXT NOT NULL,
            actionable INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.commit()


# ---------------------------------------------------------------------------
# Remote query execution (SSH + psql)
# ---------------------------------------------------------------------------

def run_remote_query(query, host=SPARKFORGE_SSH_HOST, db=SPARKFORGE_DB_NAME):
    """Execute a PostgreSQL query on the remote SparkForge DB via SSH.

    Returns a list of dicts (rows) parsed from psql JSON output.
    Returns an empty list if the query fails or returns no rows.
    """
    # Use psql with JSON array output for reliable parsing
    psql_cmd = (
        f"psql -d {db} -t -A -c "
        f"\"SELECT json_agg(t) FROM ({query.rstrip(';')}) t;\""
    )

    try:
        result = subprocess.run(
            ["ssh", host, psql_cmd],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        print(f"WARNING: SSH query timed out after 30s")
        return []
    except FileNotFoundError:
        print("ERROR: ssh command not found")
        return []

    if result.returncode != 0:
        stderr = result.stderr.strip()
        if stderr:
            print(f"WARNING: Remote query error: {stderr[:200]}")
        return []

    output = result.stdout.strip()
    if not output or output == "" or output.lower() == "null":
        return []

    try:
        rows = json.loads(output)
        return rows if isinstance(rows, list) else []
    except json.JSONDecodeError as e:
        print(f"WARNING: Failed to parse query output: {e}")
        return []


# ---------------------------------------------------------------------------
# Analysis functions
# ---------------------------------------------------------------------------

def analyze_sessions(sessions):
    """Analyze session summary data for key insights."""
    insights = []
    flagged_job_types = []

    for row in sessions:
        job_type = row.get("job_type", "unknown")
        accept_rate = float(row.get("avg_accept_rate") or 0)
        total = int(row.get("total_sessions") or 0)

        if accept_rate < ACCEPTANCE_THRESHOLD and total >= 3:
            flagged_job_types.append({
                "job_type": job_type,
                "accept_rate": accept_rate,
                "total_sessions": total,
                "total_rejected": int(row.get("total_rejected") or 0),
            })
            insights.append(
                f"LOW ACCEPTANCE: '{job_type}' has {accept_rate:.0%} acceptance "
                f"rate across {total} sessions — needs prompt review"
            )

    return insights, flagged_job_types


def analyze_confidence_calibration(calibration_rows):
    """Check if confidence scores correlate with actual acceptance."""
    insights = []

    for row in calibration_rows:
        band = row.get("confidence_band", "?")
        actual_rate = float(row.get("actual_accept_rate") or 0)
        total = int(row.get("total_items") or 0)

        if total < 5:
            continue

        # Extract the lower bound of the confidence band
        if band == "90-100%":
            expected_lower = 0.85
        elif band == "80-89%":
            expected_lower = 0.75
        elif band == "70-79%":
            expected_lower = 0.65
        elif band == "60-69%":
            expected_lower = 0.55
        else:
            expected_lower = 0.40

        gap = expected_lower - actual_rate
        if gap > 0.15:
            insights.append(
                f"OVERCONFIDENT: {band} confidence band has only "
                f"{actual_rate:.0%} actual acceptance ({total} items) — "
                f"model is overconfident by {gap:.0%}"
            )
        elif actual_rate > expected_lower + 0.20:
            insights.append(
                f"UNDERCONFIDENT: {band} confidence band has "
                f"{actual_rate:.0%} actual acceptance ({total} items) — "
                f"model could be more confident here"
            )

    return insights


def analyze_quantity_patterns(modifications):
    """Identify systematic over/under-estimation patterns."""
    insights = []

    over_estimates = []
    under_estimates = []

    for row in modifications:
        avg_pct = float(row.get("avg_pct_change") or 0)
        times = int(row.get("times_modified") or 0)
        desc = row.get("description", "?")
        job = row.get("job_type", "?")

        if times < 2:
            continue

        if avg_pct < -20:
            over_estimates.append(
                f"'{desc}' in {job}: AI suggests "
                f"{row.get('avg_ai_qty', '?')} avg, users change to "
                f"{row.get('avg_final_qty', '?')} ({avg_pct:+.0f}%)"
            )
        elif avg_pct > 20:
            under_estimates.append(
                f"'{desc}' in {job}: AI suggests "
                f"{row.get('avg_ai_qty', '?')} avg, users change to "
                f"{row.get('avg_final_qty', '?')} ({avg_pct:+.0f}%)"
            )

    if over_estimates:
        insights.append(
            f"OVER-ESTIMATING {len(over_estimates)} items: "
            + "; ".join(over_estimates[:5])
        )
    if under_estimates:
        insights.append(
            f"UNDER-ESTIMATING {len(under_estimates)} items: "
            + "; ".join(under_estimates[:5])
        )

    return insights


def analyze_rejections(rejected_items):
    """Identify the most commonly rejected suggestions."""
    insights = []

    if not rejected_items:
        return insights

    # Top 5 most rejected
    top = rejected_items[:5]
    items_list = [
        f"'{r['description']}' ({r['category']}, {r['times_rejected']}x)"
        for r in top
    ]
    insights.append(
        f"TOP REJECTED ITEMS: {', '.join(items_list)}"
    )

    # Check for high-confidence rejections (model is wrong AND confident)
    confident_rejects = [
        r for r in rejected_items
        if float(r.get("avg_confidence_when_rejected") or 0) >= 0.80
    ]
    if confident_rejects:
        items_list = [
            f"'{r['description']}' ({float(r['avg_confidence_when_rejected']):.0%} conf)"
            for r in confident_rejects[:3]
        ]
        insights.append(
            f"HIGH-CONFIDENCE REJECTIONS ({len(confident_rejects)} items): "
            + ", ".join(items_list)
        )

    return insights


def analyze_categories(category_rows):
    """Find categories with lowest acceptance rates."""
    insights = []

    for row in category_rows:
        cat = row.get("category", "?")
        rate = float(row.get("accept_rate") or 0)
        total = int(row.get("total_items") or 0)

        if total < 5:
            continue

        if rate < 0.50:
            insights.append(
                f"WEAK CATEGORY: '{cat}' has only {rate:.0%} acceptance "
                f"({total} items) — consider removing or retraining"
            )

    return insights


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------

def generate_report(sessions, rejected, modifications, calibration,
                    categories, outcomes, all_insights, flagged):
    """Generate a markdown research report."""
    today = datetime.now().strftime("%Y-%m-%d")
    lines = [
        f"# SparkForge AI Estimator Analysis — {today}",
        "",
        "## Executive Summary",
        "",
    ]

    # Summary stats
    total_sessions = sum(int(r.get("total_sessions") or 0) for r in sessions)
    total_items = sum(int(r.get("total_items") or 0) for r in sessions)
    total_accepted = sum(int(r.get("total_accepted") or 0) for r in sessions)
    total_rejected = sum(int(r.get("total_rejected") or 0) for r in sessions)
    total_modified = sum(int(r.get("total_modified") or 0) for r in sessions)

    overall_accept = total_accepted / total_items if total_items > 0 else 0

    lines.extend([
        f"- **{total_sessions}** analysis sessions across "
        f"**{len(sessions)}** job types",
        f"- **{total_items}** total suggestion items",
        f"- Overall acceptance rate: **{overall_accept:.0%}** "
        f"({total_accepted} accepted / {total_rejected} rejected / "
        f"{total_modified} modified)",
        "",
    ])

    if flagged:
        lines.append(f"**{len(flagged)} job type(s) below {ACCEPTANCE_THRESHOLD:.0%} "
                      f"threshold — prompt review needed**")
        lines.append("")

    # Actionable insights
    if all_insights:
        lines.extend(["## Actionable Insights", ""])
        for i, insight in enumerate(all_insights, 1):
            lines.append(f"{i}. {insight}")
        lines.append("")

    # Session breakdown by job type
    if sessions:
        lines.extend([
            "## Acceptance Rates by Job Type",
            "",
            "| Job Type | Sessions | Items | Accept% | Reject% | Modify% | Avg Confidence |",
            "|----------|----------|-------|---------|---------|---------|----------------|",
        ])
        for row in sessions:
            accept = float(row.get("avg_accept_rate") or 0)
            reject = float(row.get("avg_reject_rate") or 0)
            modify = float(row.get("avg_modify_rate") or 0)
            conf = float(row.get("avg_confidence") or 0)
            flag = " ⚠️" if accept < ACCEPTANCE_THRESHOLD else ""
            lines.append(
                f"| {row['job_type']}{flag} | {row['total_sessions']} | "
                f"{row['total_items']} | {accept:.0%} | {reject:.0%} | "
                f"{modify:.0%} | {conf:.0%} |"
            )
        lines.append("")

    # Confidence calibration
    if calibration:
        lines.extend([
            "## Confidence Calibration",
            "",
            "| Confidence Band | Items | Accepted | Modified | Rejected | Actual Accept% |",
            "|----------------|-------|----------|----------|----------|----------------|",
        ])
        for row in calibration:
            lines.append(
                f"| {row['confidence_band']} | {row['total_items']} | "
                f"{row['accepted']} | {row['modified']} | {row['rejected']} | "
                f"{float(row.get('actual_accept_rate') or 0):.0%} |"
            )
        lines.append("")

    # Top rejected items
    if rejected:
        lines.extend(["## Most Rejected Items", ""])
        lines.append("| Job Type | Description | Category | Rejected Count | Avg Confidence |")
        lines.append("|----------|-------------|----------|----------------|----------------|")
        for row in rejected[:15]:
            conf = float(row.get("avg_confidence_when_rejected") or 0)
            lines.append(
                f"| {row['job_type']} | {row['description']} | "
                f"{row['category']} | {row['times_rejected']} | {conf:.0%} |"
            )
        lines.append("")

    # Quantity modification patterns
    if modifications:
        lines.extend(["## Quantity Adjustment Patterns", ""])
        lines.append("| Job Type | Description | AI Qty | Final Qty | Adjustment | % Change | Count |")
        lines.append("|----------|-------------|--------|-----------|------------|----------|-------|")
        for row in modifications[:15]:
            lines.append(
                f"| {row['job_type']} | {row['description']} | "
                f"{row['avg_ai_qty']} | {row['avg_final_qty']} | "
                f"{row['avg_adjustment']} | {float(row.get('avg_pct_change') or 0):+.0f}% | "
                f"{row['times_modified']} |"
            )
        lines.append("")

    # Category breakdown
    if categories:
        lines.extend([
            "## Category Acceptance Rates",
            "",
            "| Category | Items | Accepted | Modified | Rejected | Accept% |",
            "|----------|-------|----------|----------|----------|---------|",
        ])
        for row in categories:
            rate = float(row.get("accept_rate") or 0)
            flag = " ⚠️" if rate < 0.50 else ""
            lines.append(
                f"| {row['category']}{flag} | {row['total_items']} | "
                f"{row['accepted']} | {row['modified']} | {row['rejected']} | "
                f"{rate:.0%} |"
            )
        lines.append("")

    # Outcome tracking
    if outcomes:
        lines.extend([
            "## Outcome Tracking",
            "",
            "| Job Type | Outcome | Sessions | Avg Accuracy |",
            "|----------|---------|----------|--------------|",
        ])
        for row in outcomes:
            acc = float(row.get("avg_accuracy") or 0)
            lines.append(
                f"| {row['job_type']} | {row['outcome_status']} | "
                f"{row['session_count']} | {acc:.0%} |"
            )
        lines.append("")

    # Recommendations
    lines.extend(["## Recommendations", ""])
    if flagged:
        for f in flagged:
            lines.append(
                f"1. **Review prompt for '{f['job_type']}'** — "
                f"{f['accept_rate']:.0%} acceptance across "
                f"{f['total_sessions']} sessions"
            )
    if not all_insights and not flagged:
        lines.append("- No actionable issues found. AI estimator performing well.")
    lines.append("")

    lines.extend([
        "---",
        f"Generated: {datetime.now().isoformat()}",
        f"Threshold: {ACCEPTANCE_THRESHOLD:.0%} minimum acceptance rate",
    ])

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# TheForge integration
# ---------------------------------------------------------------------------

def store_findings(conn, summary, findings, actionable, dry_run=False):
    """Store research findings in TheForge database."""
    if dry_run:
        print("DRY RUN: Skipping TheForge insert")
        return

    today = datetime.now().strftime("%Y-%m-%d")
    conn.execute(
        """INSERT INTO research_findings
           (project_id, report_type, report_date, summary, findings_json, actionable)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (SPARKFORGE_PROJECT_ID, "estimator-analysis", today,
         summary, json.dumps(findings), 1 if actionable else 0),
    )
    conn.commit()


def create_review_task(conn, flagged_types, dry_run=False):
    """Create a TheForge task to review prompts for flagged job types.

    Only creates one task per run to avoid spamming.
    """
    if dry_run or not flagged_types:
        return

    today = datetime.now().strftime("%Y-%m-%d")

    # Check if a review task already exists this week
    cur = conn.cursor()
    cur.execute("""
        SELECT id FROM tasks
        WHERE project_id = ?
        AND title LIKE '%AI prompt review%'
        AND status IN ('todo', 'in_progress')
        AND created_at >= datetime('now', '-7 days')
        LIMIT 1
    """, (SPARKFORGE_PROJECT_ID,))

    if cur.fetchone():
        print("INFO: Prompt review task already exists this week, skipping")
        return

    types_str = ", ".join(f['job_type'] for f in flagged_types)
    details = "\n".join(
        f"- {f['job_type']}: {f['accept_rate']:.0%} acceptance "
        f"({f['total_sessions']} sessions, {f['total_rejected']} rejections)"
        for f in flagged_types
    )

    description = (
        f"Weekly estimator analysis ({today}) found job types below "
        f"{ACCEPTANCE_THRESHOLD:.0%} acceptance threshold:\n\n"
        f"{details}\n\n"
        f"Review and update the AI system prompt for these job types. "
        f"Check the full report at research/estimator-analysis-{today}.md"
    )

    conn.execute(
        """INSERT INTO tasks (project_id, title, description, status, priority)
           VALUES (?, ?, ?, 'todo', 'medium')""",
        (SPARKFORGE_PROJECT_ID,
         f"[AI] Prompt review needed: {types_str}",
         description),
    )
    conn.commit()
    print(f"CREATED: TheForge task for prompt review ({types_str})")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    # Parse arguments
    db_path = None
    print_report = False
    dry_run = False
    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--db" and i + 1 < len(args):
            db_path = args[i + 1]
            i += 2
        elif args[i] == "--print":
            print_report = True
            i += 1
        elif args[i] == "--dry-run":
            dry_run = True
            i += 1
        else:
            i += 1

    print(f"=== SparkForge Estimator Research — {datetime.now().isoformat()} ===")

    # 1. Query SparkForge DB via SSH
    print("Querying SparkForge DB on apocrypha-vm...")

    sessions = run_remote_query(QUERY_SESSIONS_SUMMARY)
    rejected = run_remote_query(QUERY_REJECTED_ITEMS)
    modifications = run_remote_query(QUERY_QUANTITY_MODIFICATIONS)
    calibration = run_remote_query(QUERY_CONFIDENCE_CALIBRATION)
    categories = run_remote_query(QUERY_CATEGORY_ACCEPTANCE)
    outcomes = run_remote_query(QUERY_OUTCOME_ACCURACY)

    total_sessions = sum(int(r.get("total_sessions") or 0) for r in sessions)
    print(f"Retrieved: {total_sessions} sessions, {len(rejected)} rejection "
          f"patterns, {len(modifications)} modification patterns")

    if total_sessions == 0:
        print("No analysis sessions found. Exiting.")
        return

    # 2. Run analysis
    print("Analyzing patterns...")

    all_insights = []
    session_insights, flagged = analyze_sessions(sessions)
    all_insights.extend(session_insights)
    all_insights.extend(analyze_confidence_calibration(calibration))
    all_insights.extend(analyze_quantity_patterns(modifications))
    all_insights.extend(analyze_rejections(rejected))
    all_insights.extend(analyze_categories(categories))

    print(f"Found {len(all_insights)} insights, "
          f"{len(flagged)} flagged job types")

    # 3. Generate report
    report = generate_report(
        sessions, rejected, modifications, calibration,
        categories, outcomes, all_insights, flagged,
    )

    # 4. Save report to research directory
    report_dir = Path(__file__).resolve().parent.parent / "SparkForge" / REPORT_DIR_NAME
    report_dir.mkdir(parents=True, exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")
    report_path = report_dir / f"{REPORT_PREFIX}-{today}.md"
    with open(report_path, "w") as f:
        f.write(report)
    print(f"Report saved: {report_path}")

    # 5. Store in TheForge
    db_path = find_db(db_path)
    print(f"TheForge DB: {db_path}")
    conn = get_db(db_path)

    try:
        ensure_research_table(conn)

        summary = (
            f"{total_sessions} sessions analyzed. "
            f"{len(all_insights)} insights. "
            f"{len(flagged)} job types flagged."
        )
        findings_data = {
            "date": today,
            "total_sessions": total_sessions,
            "insights": all_insights,
            "flagged_job_types": flagged,
        }

        store_findings(conn, summary, findings_data,
                       actionable=len(flagged) > 0, dry_run=dry_run)

        # 6. Create review task if needed
        if flagged:
            create_review_task(conn, flagged, dry_run=dry_run)
    finally:
        conn.close()

    # Output
    if print_report:
        print("\n" + report)

    print(f"\nDone! {len(all_insights)} insights, "
          f"{len(flagged)} actions needed.")


if __name__ == "__main__":
    main()
