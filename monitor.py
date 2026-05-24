#!/usr/bin/env python3
"""
Monitoring and Alerting for the System Intelligence Scanner.
Runs periodically to detect anomalies and send alerts.
"""

import json
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone

# ──────────────────────────────────────────────────────────────
# Alerting Channels
# ──────────────────────────────────────────────────────────────

def send_slack_alert(message: str, webhook_url: str = None) -> bool:
    """Send alert via Slack webhook. Returns True on success."""
    url = webhook_url or os.environ.get("SLACK_MONITOR_WEBHOOK")
    if not url:
        print("[monitor] No Slack webhook configured — printing alert locally")
        print(message)
        return False

    try:
        import urllib.request
        payload = json.dumps({"text": message}).encode()
        req = urllib.request.Request(url, data=payload, method="POST")
        req.add_header("Content-Type", "application/json")
        resp = urllib.request.urlopen(req, timeout=10)
        return resp.status == 200
    except Exception as e:
        print(f"[monitor] Slack alert failed: {e}")
        return False


def send_stdout_alert(message: str) -> bool:
    """Fallback: print alert to stdout (captured by cron)."""
    print(f"[ALERT] {message}")
    return True


# ──────────────────────────────────────────────────────────────
# Monitoring Checks
# ──────────────────────────────────────────────────────────────

def check_kanban_crash_loops(db_path: str = None) -> list:
    """Detect tasks in crash-loop: running status with dead PIDs."""
    db_path = db_path or os.path.expanduser("~/.hermes/kanban.db")
    alerts = []

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Find tasks marked 'running' that have crashed predecessors
        cursor.execute("""
            SELECT id, title FROM tasks WHERE status = 'running'
        """)
        running_tasks = cursor.fetchall()

        for task_id, title in running_tasks:
            # Check last 3 runs
            cursor.execute("""
                SELECT outcome FROM task_runs
                WHERE task_id = ? ORDER BY id DESC LIMIT 3
            """, (task_id,))
            outcomes = [r[0] for r in cursor.fetchall()]

            if outcomes and outcomes[0] is None:
                # Currently running — check if any prior runs crashed
                if outcomes[1:] and all(o == "crashed" for o in outcomes[1:] if o):
                    alerts.append({
                        "task_id": task_id,
                        "title": title,
                        "issue": "crash-loop detected",
                        "detail": (
                            f"Task '{title}' ({task_id}) is 'running' but "
                            f"previous {len(outcomes[1:])} runs all crashed. "
                            f"Likely zombie PID."
                        ),
                    })

        conn.close()
    except Exception as e:
        alerts.append({
            "task_id": None,
            "title": "monitor-error",
            "issue": f"db check failed: {e}",
            "detail": str(e),
        })

    return alerts


def check_cron_failures(jobs_path: str = None) -> list:
    """Detect cron jobs with recent failures."""
    jobs_path = jobs_path or os.path.expanduser("~/.hermes/cron/jobs.json")
    alerts = []

    try:
        with open(jobs_path) as f:
            data = json.load(f)

        for job in data.get("jobs", []):
            if job.get("enabled") and job.get("last_status") == "error":
                alerts.append({
                    "task_id": None,
                    "title": f"cron: {job.get('name', 'unknown')}",
                    "issue": "cron job failing",
                    "detail": (
                        f"Cron job '{job.get('name')}' failed: "
                        f"{job.get('last_error', 'unknown error')}"
                    ),
                })
    except Exception as e:
        alerts.append({
            "task_id": None,
            "title": "cron-check-error",
            "issue": f"cron check failed: {e}",
            "detail": str(e),
        })

    return alerts


def check_service_health(health_url: str = "http://127.0.0.1:8642/health") -> list:
    """Check if workspace service is alive."""
    alerts = []

    try:
        import urllib.request
        req = urllib.request.Request(health_url, method="GET")
        resp = urllib.request.urlopen(req, timeout=5)
        if resp.status != 200:
            alerts.append({
                "task_id": None,
                "title": "workspace-health",
                "issue": "workspace unhealthy",
                "detail": f"Health endpoint returned status {resp.status}",
            })
    except Exception as e:
        alerts.append({
            "task_id": None,
            "title": "workspace-health",
            "issue": "workspace unreachable",
            "detail": str(e),
        })

    return alerts


# ──────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────

def main():
    alerts = []

    # Run all checks
    alerts.extend(check_kanban_crash_loops())
    alerts.extend(check_cron_failures())
    alerts.extend(check_service_health())

    # Report
    if alerts:
        print(f"\n{'='*60}")
        print(f"MONITOR REPORT — {datetime.now(timezone.utc).isoformat()}")
        print(f"{'='*60}")
        print(f"⚠️  {len(alerts)} alert(s) detected:\n")

        for a in alerts:
            print(f"  • [{a['title']}] {a['issue']}")
            print(f"    {a['detail']}\n")

        # Send summary alert
        summary = (
            f"*Scanner Monitor — {len(alerts)} alerts*\n"
        )
        for a in alerts:
            summary += f"• *{a['title']}*: {a['issue']}\n  {a['detail']}\n"

        send_slack_alert(summary)
        return 1
    else:
        print(f"\n{'='*60}")
        print(f"MONITOR REPORT — {datetime.now(timezone.utc).isoformat()}")
        print(f"{'='*60}")
        print("✅ No alerts — system looks healthy.\n")
        return 0


if __name__ == "__main__":
    exit(main())
