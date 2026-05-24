#!/usr/bin/env python3
"""
System Intelligence Scanner — Core Scanning Engine
Orchestrates system state collection, gap analysis, and improvement generation.
Replaces the generic dreamer agent with real system context analysis.
"""

import json
import os
import sys
from datetime import datetime, timezone

from context_awareness import (
    collect_system_state,
    SystemStateReport,
    print_report,
)

# ──────────────────────────────────────────────────────────────
# Improvement Generator
# ──────────────────────────────────────────────────────────────

def generate_improvement_tasks(report: SystemStateReport) -> list:
    """Generate actionable Kanban tasks from system state gaps."""
    tasks = []

    # Fix failing cron jobs
    for job in report.failing_cron_jobs:
        if "script path" in (job.last_error or ""):
            tasks.append({
                "title": f"Fix script path for cron job '{job.name}'",
                "description": (
                    f"Job '{job.name}' is blocked because the script path "
                    f"resolves outside the expected scripts directory. "
                    f"Error: {job.last_error}"
                ),
                "priority": 1,
            })
        elif "threat pattern" in (job.last_error or ""):
            tasks.append({
                "title": f"Review and fix prompt for '{job.name}' cron job",
                "description": (
                    f"Job '{job.name}' is blocked by security filter. "
                    f"The prompt matches threat pattern. "
                    f"Error: {job.last_error}"
                ),
                "priority": 2,
            })

    # Fix blocked Kanban tasks
    blocked_tasks = [t for t in report.kanban_tasks if t.status == "blocked"]
    for task in blocked_tasks:
        tasks.append({
            "title": f"Unblock Kanban task: {task.title}",
            "description": (
                f"Task '{task.title}' ({task.id}) is blocked. "
                f"Investigate and resolve the blockage."
            ),
            "priority": 1,
        })

    # Knowledge mining opportunity
    if report.knowledge_page_count > 50 and not report.slack_index_exists:
        tasks.append({
            "title": "Analyze Slack index for self-improvement patterns",
            "description": (
                f"Knowledge base has {report.knowledge_page_count} pages "
                f"but Slack index is not being analyzed. "
                f"Mine Slack conversations for improvement opportunities."
            ),
            "priority": 2,
        })

    return tasks


def format_report(report: SystemStateReport) -> str:
    """Format a concise Slack-ready report."""
    lines = []
    lines.append(f"*System Intelligence Scan — {report.timestamp}*")
    lines.append("")

    # Health summary
    if report.service_health:
        lines.append(f"• Workspace: {report.service_health.workspace}")
        lines.append(f"• Dashboard: {report.service_health.dashboard}")
        if report.service_health.uptime_hours:
            lines.append(f"• Uptime: {report.service_health.uptime_hours}h")

    # Cron health
    ok_count = sum(1 for j in report.cron_jobs if j.last_status == "ok")
    fail_count = len(report.failing_cron_jobs)
    lines.append(f"• Cron jobs: {ok_count} ok, {fail_count} failing ({len(report.cron_jobs)} total)")

    # Kanban
    done_count = sum(1 for t in report.kanban_tasks if t.status == "done")
    blocked_count = sum(1 for t in report.kanban_tasks if t.status == "blocked")
    todo_count = sum(1 for t in report.kanban_tasks if t.status in ("todo", "ready"))
    lines.append(f"• Kanban: {done_count} done, {blocked_count} blocked, {todo_count} todo")

    # Knowledge
    lines.append(f"• Knowledge: {report.knowledge_page_count} pages")
    slack_status = "analyzed" if report.slack_index_exists else "not analyzed"
    lines.append(f"• Slack index: {slack_status}")

    # Gaps
    if report.kanban_gaps:
        lines.append("")
        lines.append("*Improvement Opportunities:*")
        for g in report.kanban_gaps:
            lines.append(f"  ⚠️ {g}")

    # Improvement tasks
    improvements = generate_improvement_tasks(report)
    if improvements:
        lines.append("")
        lines.append("*Suggested New Tasks:*")
        for t in improvements:
            lines.append(f"  📋 {t['title']} (P{t['priority']})")

    return "\n".join(lines)


def save_report(report: SystemStateReport) -> str:
    """Save the report to a timestamped file for the knowledge base."""
    reports_dir = os.path.expanduser("~/.hermes/knowledge/pages/scanner-reports")
    os.makedirs(reports_dir, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d-%H%M%S")
    filename = f"scan-{timestamp}.md"
    filepath = os.path.join(reports_dir, filename)

    report_text = format_report(report)
    report_md = f"""# System Intelligence Scan — {timestamp}

{report_text}

## Raw Data
- Cron jobs: {len(report.cron_jobs)} total, {len(report.failing_cron_jobs)} failing
- Kanban tasks: {len(report.kanban_tasks)} total
- Knowledge pages: {report.knowledge_page_count}
- Slack index: {'exists' if report.slack_index_exists else 'none'}
"""

    with open(filepath, "w") as f:
        f.write(report_md)

    return filepath


def main():
    report = collect_system_state()
    print_report(report)

    # Save report to knowledge base
    saved_path = save_report(report)
    print(f"\nReport saved to: {saved_path}")

    # Generate improvement tasks
    improvements = generate_improvement_tasks(report)
    if improvements:
        print(f"\n📋 Generated {len(improvements)} improvement task suggestions:")
        for t in improvements:
            print(f"  • {t['title']} (P{t['priority']})")
    else:
        print("\n✅ No improvement tasks needed — system looks healthy.")

    return 0


if __name__ == "__main__":
    exit(main())
