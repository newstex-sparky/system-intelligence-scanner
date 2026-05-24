#!/usr/bin/env python3
"""
Context-Awareness Module — System Intelligence Scanner
Reads actual system state and returns a structured report of improvement opportunities.

This module is the first component of the Context-Aware System Intelligence Scanner.
It replaces the generic dreamer agent with real system context analysis.
"""

import json
import os
import sqlite3
import subprocess
import time
from datetime import datetime, timezone
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

# ──────────────────────────────────────────────────────────────
# Data structures
# ──────────────────────────────────────────────────────────────

@dataclass
class CronJobState:
    """Health of a single cron job."""
    name: str
    enabled: bool
    last_status: Optional[str]
    last_error: Optional[str]
    last_delivery_error: Optional[str]
    next_run_at: Optional[str]
    last_run_at: Optional[str]
    completed_count: int

@dataclass
class KanbanTask:
    """A task on the Kanban board."""
    id: str
    title: str
    status: str
    priority: int

@dataclass
class ServiceHealth:
    """Health of Hermes services."""
    workspace: Optional[str]
    dashboard: Optional[str]
    gateway: Optional[str]
    uptime_hours: Optional[float]

@dataclass
class SystemStateReport:
    """Full system state snapshot."""
    timestamp: str
    cron_jobs: List[CronJobState] = field(default_factory=list)
    failing_cron_jobs: List[CronJobState] = field(default_factory=list)
    kanban_tasks: List[KanbanTask] = field(default_factory=list)
    kanban_gaps: List[str] = field(default_factory=list)
    service_health: Optional[ServiceHealth] = None
    knowledge_page_count: int = 0
    slack_index_exists: bool = False
    slack_conversations_count: int = 0
    improvement_opportunities: List[str] = field(default_factory=list)


# ──────────────────────────────────────────────────────────────
# Collectors
# ──────────────────────────────────────────────────────────────

def collect_cron_state() -> List[CronJobState]:
    """Read cron jobs.json and return structured state."""
    jobs_path = os.path.expanduser("~/.hermes/cron/jobs.json")
    states = []
    try:
        with open(jobs_path) as f:
            data = json.load(f)
        for job in data.get("jobs", []):
            state = CronJobState(
                name=job.get("name", "unnamed"),
                enabled=job.get("enabled", False),
                last_status=job.get("last_status"),
                last_error=job.get("last_error"),
                last_delivery_error=job.get("last_delivery_error"),
                next_run_at=job.get("next_run_at"),
                last_run_at=job.get("last_run_at"),
                completed_count=job.get("repeat", {}).get("completed", 0),
            )
            states.append(state)
    except Exception as e:
        print(f"[context-awareness] Error reading cron jobs: {e}")
    return states


def collect_kanban_state() -> List[KanbanTask]:
    """Read Kanban board from SQLite."""
    db_path = os.path.expanduser("~/.hermes/kanban.db")
    tasks = []
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, title, status, priority FROM tasks ORDER BY created_at"
        )
        for row in cursor.fetchall():
            tasks.append(KanbanTask(id=row[0], title=row[1], status=row[2], priority=row[3]))
        conn.close()
    except Exception as e:
        print(f"[context-awareness] Error reading kanban: {e}")
    return tasks


def check_service_health() -> Optional[ServiceHealth]:
    """Check if workspace and dashboard are responding."""
    health = ServiceHealth(None, None, None, None)
    try:
        import urllib.request
        req = urllib.request.Request("http://127.0.0.1:8642/health", method="GET")
        resp = urllib.request.urlopen(req, timeout=5)
        if resp.status == 200:
            health.workspace = "ok"
    except Exception as e:
        health.workspace = f"unreachable: {e}"

    try:
        import urllib.request
        req = urllib.request.Request("http://127.0.0.1:8642/api/kanban", method="GET")
        resp = urllib.request.urlopen(req, timeout=5)
        if resp.status == 200:
            health.dashboard = "ok"
    except Exception as e:
        health.dashboard = f"unreachable: {e}"

    # Estimate uptime from process
    try:
        result = subprocess.run(
            ["ps", "-eo", "pid,etimes,comm"],
            capture_output=True, text=True, timeout=5
        )
        for line in result.stdout.splitlines():
            if "hermes-workspace" in line or "node" in line:
                parts = line.strip().split()
                if len(parts) >= 3:
                    try:
                        etime = int(parts[1])
                        health.uptime_hours = round(etime / 3600, 1)
                    except ValueError:
                        pass
                break
    except Exception:
        pass

    return health


def count_knowledge_pages() -> int:
    """Count pages in the knowledge base."""
    kb_path = os.path.expanduser("~/.hermes/knowledge/pages")
    try:
        files = os.listdir(kb_path)
        return len(files)
    except Exception:
        return 0


def check_slack_index() -> tuple:
    """Check if Slack index exists and count conversations."""
    slack_path = os.path.expanduser("~/.hermes/knowledge/slack-index/slack_messages.json")
    try:
        if os.path.exists(slack_path):
            with open(slack_path) as f:
                data = json.load(f)
            if isinstance(data, list):
                return True, len(data)
            elif isinstance(data, dict):
                return True, len(data.get("messages", data.get("conversations", [data])))
            return True, 1
        return False, 0
    except Exception:
        return False, 0


# ──────────────────────────────────────────────────────────────
# Gap Analysis
# ──────────────────────────────────────────────────────────────

def analyze_gaps(
    cron_states: List[CronJobState],
    kanban_tasks: List[KanbanTask],
) -> List[str]:
    """Identify improvement opportunities from system state."""
    gaps = []

    # Failing cron jobs
    failing = [j for j in cron_states if j.last_status == "error" and j.enabled]
    if failing:
        gaps.append(
            f"{len(failing)} cron jobs failing: "
            + ", ".join(f"'{j.name}' ({j.last_error})" for j in failing)
        )

    # Delivery errors
    delivery_issues = [j for j in cron_states if j.last_delivery_error and j.enabled]
    if delivery_issues:
        gaps.append(
            f"{len(delivery_issues)} jobs with delivery failures: "
            + ", ".join(j.name for j in delivery_issues)
        )

    # Kanban blocked tasks
    blocked = [t for t in kanban_tasks if t.status == "blocked"]
    if blocked:
        gaps.append(
            f"{len(blocked)} Kanban tasks blocked: "
            + ", ".join(f"'{t.title}' ({t.id})" for t in blocked)
        )

    # Kanban tasks with no sub-tasks (stale)
    ready = [t for t in kanban_tasks if t.status == "ready" and t.priority == 0]
    if ready:
        gaps.append(
            f"{len(ready)} ready tasks at priority 0 (may need prioritization): "
            + ", ".join(f"'{t.title}'" for t in ready)
        )

    return gaps


# ──────────────────────────────────────────────────────────────
# Main entry point
# ──────────────────────────────────────────────────────────────

def collect_system_state() -> SystemStateReport:
    """Gather full system state and return structured report."""
    timestamp = datetime.now(timezone.utc).isoformat()

    cron_states = collect_cron_state()
    failing = [j for j in cron_states if j.last_status == "error" and j.enabled]
    kanban = collect_kanban_state()
    health = check_service_health()
    kb_count = count_knowledge_pages()
    slack_exists, slack_count = check_slack_index()
    gaps = analyze_gaps(cron_states, kanban)

    report = SystemStateReport(
        timestamp=timestamp,
        cron_jobs=cron_states,
        failing_cron_jobs=failing,
        kanban_tasks=kanban,
        kanban_gaps=gaps,
        service_health=health,
        knowledge_page_count=kb_count,
        slack_index_exists=slack_exists,
        slack_conversations_count=slack_count,
        improvement_opportunities=gaps,
    )
    return report


def print_report(report: SystemStateReport) -> None:
    """Pretty-print the system state report."""
    print("=" * 60)
    print(f"SYSTEM STATE REPORT — {report.timestamp}")
    print("=" * 60)

    # Service health
    if report.service_health:
        print(f"\nService Health:")
        print(f"  Workspace:  {report.service_health.workspace}")
        print(f"  Dashboard:  {report.service_health.dashboard}")
        if report.service_health.uptime_hours:
            print(f"  Uptime:     {report.service_health.uptime_hours}h")

    # Knowledge base
    print(f"\nKnowledge Base:")
    print(f"  Pages:      {report.knowledge_page_count}")
    print(f"  Slack idx:  {'exists' if report.slack_index_exists else 'none'} ({report.slack_conversations_count} conversations)")

    # Cron jobs
    print(f"\nCron Jobs ({len(report.cron_jobs)} total):")
    for j in report.cron_jobs:
        status_marker = "✓" if j.last_status == "ok" else "✗" if j.last_status == "error" else "?"
        print(f"  {status_marker} {j.name} (completed {j.completed_count}x)")
        if j.last_error:
            print(f"     Error: {j.last_error}")

    # Failing jobs
    if report.failing_cron_jobs:
        print(f"\n⚠️  Failing Jobs:")
        for j in report.failing_cron_jobs:
            print(f"  ✗ {j.name}")
            if j.last_error:
                print(f"     {j.last_error}")
            if j.last_delivery_error:
                print(f"     Delivery: {j.last_delivery_error}")

    # Kanban board
    print(f"\nKanban Board ({len(report.kanban_tasks)} tasks):")
    for t in report.kanban_tasks:
        status_icon = {"done": "✓", "blocked": "⊘", "in_progress": "●", "ready": "○", "todo": "·"}
        icon = status_icon.get(t.status, "·")
        print(f"  {icon} [{t.status}] {t.title}")

    # Gaps
    if report.kanban_gaps:
        print(f"\n🔍 Improvement Opportunities ({len(report.kanban_gaps)}):")
        for g in report.kanban_gaps:
            print(f"  • {g}")
    else:
        print(f"\n✅ No gaps detected — system looks healthy.")

    print()


if __name__ == "__main__":
    report = collect_system_state()
    print_report(report)
