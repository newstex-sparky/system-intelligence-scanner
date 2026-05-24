"""Tests for context_awareness module — System Intelligence Scanner."""

import json
import os
import sqlite3
import tempfile
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone

import pytest

# Add parent dir to path so we can import the module
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from context_awareness import (
    CronJobState,
    KanbanTask,
    ServiceHealth,
    SystemStateReport,
    collect_cron_state,
    collect_kanban_state,
    check_service_health,
    count_knowledge_pages,
    check_slack_index,
    analyze_gaps,
    collect_system_state,
    print_report,
)


class TestCollectCronState:
    def test_reads_jobs_from_file(self):
        """Should parse cron jobs.json into CronJobState objects."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({
                "jobs": [
                    {
                        "name": "test-job",
                        "enabled": True,
                        "last_status": "ok",
                        "last_error": None,
                        "last_delivery_error": None,
                        "next_run_at": "2026-05-24T12:00:00Z",
                        "last_run_at": "2026-05-24T11:00:00Z",
                        "repeat": {"completed": 5},
                    }
                ]
            }, f)
            temp_path = f.name

        try:
            with patch("context_awareness.os.path.expanduser", return_value=temp_path):
                states = collect_cron_state()
                assert len(states) == 1
                assert states[0].name == "test-job"
                assert states[0].enabled is True
                assert states[0].last_status == "ok"
                assert states[0].completed_count == 5
        finally:
            os.unlink(temp_path)

    def test_empty_jobs_list(self):
        """Should handle empty jobs list gracefully."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"jobs": []}, f)
            temp_path = f.name

        try:
            with patch("context_awareness.os.path.expanduser", return_value=temp_path):
                states = collect_cron_state()
                assert len(states) == 0
        finally:
            os.unlink(temp_path)

    def test_missing_file_returns_empty(self):
        """Should return empty list when file doesn't exist."""
        with patch("context_awareness.os.path.expanduser", return_value="/nonexistent/path.json"):
            states = collect_cron_state()
            assert len(states) == 0

    def test_bad_json_returns_empty(self):
        """Should handle corrupt JSON gracefully."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("not valid json")
            temp_path = f.name

        try:
            with patch("context_awareness.os.path.expanduser", return_value=temp_path):
                states = collect_cron_state()
                assert len(states) == 0
        finally:
            os.unlink(temp_path)


class TestCollectKanbanState:
    def test_reads_tasks_from_sqlite(self):
        """Should parse Kanban SQLite into KanbanTask objects."""
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE tasks (id TEXT, title TEXT, status TEXT, priority INT, created_at INT)")
        conn.execute(
            "INSERT INTO tasks VALUES ('t_test', 'Test Task', 'todo', 0, 1000000)"
        )
        conn.commit()

        with patch("context_awareness.sqlite3.connect", return_value=conn):
            tasks = collect_kanban_state()
            assert len(tasks) == 1
            assert tasks[0].id == "t_test"
            assert tasks[0].title == "Test Task"
            assert tasks[0].status == "todo"
            assert tasks[0].priority == 0

    def test_empty_db_returns_empty(self):
        """Should handle empty database gracefully."""
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE tasks (id TEXT, title TEXT, status TEXT, priority INT, created_at INT)")
        conn.commit()

        with patch("context_awareness.sqlite3.connect", return_value=conn):
            tasks = collect_kanban_state()
            assert len(tasks) == 0


class TestServiceHealth:
    @patch("urllib.request.urlopen")
    def test_workspace_healthy(self, mock_urlopen):
        """Should report workspace ok when health endpoint returns 200."""
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_urlopen.return_value = mock_resp

        with patch("context_awareness.subprocess.run") as mock_run:
            mock_run.return_value.stdout = "12345 3600 hermes-workspace\n"
            health = check_service_health()
            assert health.workspace == "ok"
            assert health.uptime_hours == 1.0

    @patch("urllib.request.urlopen")
    def test_workspace_unreachable(self, mock_urlopen):
        """Should report unreachable on connection error."""
        mock_urlopen.side_effect = Exception("Connection refused")

        with patch("context_awareness.subprocess.run") as mock_run:
            mock_run.return_value.stdout = ""
            health = check_service_health()
            assert "unreachable" in (health.workspace or "")


class TestCountKnowledgePages:
    def test_counts_directory(self):
        """Should count files in knowledge pages directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create some fake page files
            for i in range(3):
                with open(os.path.join(tmpdir, f"page_{i}.md"), "w") as f:
                    f.write("# test")

            with patch("context_awareness.os.path.expanduser", return_value=tmpdir):
                count = count_knowledge_pages()
                assert count == 3

    def test_missing_directory(self):
        """Should return 0 when directory doesn't exist."""
        with patch("context_awareness.os.path.expanduser", return_value="/nonexistent/path"):
            count = count_knowledge_pages()
            assert count == 0


class TestCheckSlackIndex:
    def test_no_file(self):
        """Should return False, 0 when file doesn't exist."""
        with patch("context_awareness.os.path.exists", return_value=False):
            exists, count = check_slack_index()
            assert not exists
            assert count == 0

    def test_list_format(self):
        """Should parse a JSON list of messages."""
        with patch("context_awareness.os.path.exists", return_value=True):
            with patch("builtins.open") as mock_open:
                mock_open.return_value.__enter__ = MagicMock()
                mock_open.return_value.__enter__.return_value.read.return_value = json.dumps(["msg1", "msg2"])

                exists, count = check_slack_index()
                assert exists
                assert count == 2

    def test_dict_format(self):
        """Should parse a JSON dict with messages key."""
        with patch("context_awareness.os.path.exists", return_value=True):
            with patch("builtins.open") as mock_open:
                mock_open.return_value.__enter__ = MagicMock()
                mock_open.return_value.__enter__.return_value.read.return_value = json.dumps({"messages": ["a", "b", "c"]})

                exists, count = check_slack_index()
                assert exists
                assert count == 3


class TestAnalyzeGaps:
    def test_failing_cron_jobs(self):
        """Should flag enabled cron jobs with error status."""
        jobs = [
            CronJobState("job1", enabled=True, last_status="error", last_error="timeout",
                         last_delivery_error=None, next_run_at=None, last_run_at=None, completed_count=0),
            CronJobState("job2", enabled=True, last_status="ok", last_error=None,
                         last_delivery_error=None, next_run_at=None, last_run_at=None, completed_count=0),
        ]
        gaps = analyze_gaps(jobs, [])
        assert len(gaps) >= 1
        assert "job1" in gaps[0]

    def test_blocked_tasks(self):
        """Should flag blocked Kanban tasks."""
        tasks = [
            KanbanTask("t_1", "Blocked Task", "blocked", 0),
            KanbanTask("t_2", "Done Task", "done", 0),
        ]
        gaps = analyze_gaps([], tasks)
        assert len(gaps) >= 1
        assert "Blocked Task" in gaps[0]

    def test_ready_tasks_at_priority_zero(self):
        """Should flag ready tasks at priority 0 as needing prioritization."""
        tasks = [
            KanbanTask("t_1", "Ready Task", "ready", 0),
            KanbanTask("t_2", "High Pri", "ready", 2),
        ]
        gaps = analyze_gaps([], tasks)
        ready_gaps = [g for g in gaps if "ready" in g and "prioritization" in g]
        assert len(ready_gaps) >= 1
        assert "Ready Task" in ready_gaps[0]

    def test_delivery_issues(self):
        """Should flag jobs with delivery errors."""
        jobs = [
            CronJobState("delivery-job", enabled=True, last_status="ok", last_error=None,
                         last_delivery_error="channel not found", next_run_at=None, last_run_at=None, completed_count=0),
        ]
        gaps = analyze_gaps(jobs, [])
        delivery_gaps = [g for g in gaps if "delivery" in g]
        assert len(delivery_gaps) >= 1
        assert "delivery-job" in delivery_gaps[0]


class TestCollectSystemState:
    def test_integration(self):
        """Should collect all system state and return a complete report."""
        with patch("context_awareness.collect_cron_state") as mock_cron, \
             patch("context_awareness.collect_kanban_state") as mock_kanban, \
             patch("context_awareness.check_service_health") as mock_health, \
             patch("context_awareness.count_knowledge_pages") as mock_kb, \
             patch("context_awareness.check_slack_index") as mock_slack:

            mock_cron.return_value = [CronJobState("test", True, "ok", None, None, None, None, 0)]
            mock_kanban.return_value = [KanbanTask("t_1", "Test", "todo", 0)]
            mock_health.return_value = ServiceHealth("ok", "ok", None, 1.0)
            mock_kb.return_value = 42
            mock_slack.return_value = (True, 10)

            report = collect_system_state()
            assert report.timestamp is not None
            assert len(report.cron_jobs) == 1
            assert len(report.kanban_tasks) == 1
            assert report.service_health.workspace == "ok"
            assert report.knowledge_page_count == 42
            assert report.slack_index_exists is True
            assert report.slack_conversations_count == 10


class TestPrintReport:
    def test_outputs_to_stdout(self, capsys):
        """Should print report to stdout without crashing."""
        report = SystemStateReport(
            timestamp="2026-05-24T12:00:00",
            cron_jobs=[CronJobState("ok-job", True, "ok", None, None, None, None, 5)],
            failing_cron_jobs=[],
            kanban_tasks=[KanbanTask("t_done", "Done", "done", 0)],
            kanban_gaps=[],
            service_health=ServiceHealth("ok", "ok", None, 1.5),
            knowledge_page_count=42,
            slack_index_exists=True,
            slack_conversations_count=10,
            improvement_opportunities=[],
        )
        print_report(report)
        captured = capsys.readouterr()
        assert "SYSTEM STATE REPORT" in captured.out
        assert "ok-job" in captured.out
        assert "Done" in captured.out
        assert "42" in captured.out


class TestScannerModule:
    """Integration tests for scanner.py."""

    def test_generate_improvement_tasks(self):
        """Should generate tasks from gaps in the report."""
        from scanner import generate_improvement_tasks

        report = SystemStateReport(
            timestamp="2026-05-24T12:00:00",
            cron_jobs=[
                CronJobState("fail-job", True, "error", "script path resolves outside",
                             None, None, None, 0),
            ],
            failing_cron_jobs=[
                CronJobState("fail-job", True, "error", "script path resolves outside",
                             None, None, None, 0),
            ],
            kanban_tasks=[
                KanbanTask("t_blocked", "Blocked Task", "blocked", 0),
            ],
            kanban_gaps=["1 cron job failing", "1 blocked task"],
            service_health=ServiceHealth("ok", "ok", None, 1.5),
            knowledge_page_count=100,
            slack_index_exists=False,
            slack_conversations_count=0,
            improvement_opportunities=["1 cron job failing", "1 blocked task"],
        )

        tasks = generate_improvement_tasks(report)
        assert len(tasks) >= 2

        # Should have at least one fix-script-path task
        path_tasks = [t for t in tasks if "script path" in t["title"]]
        assert len(path_tasks) >= 1

        # Should have at least one unblock task
        unblock_tasks = [t for t in tasks if "Unblock" in t["title"]]
        assert len(unblock_tasks) >= 1

    def test_format_report(self):
        """Should format report without crashing."""
        from scanner import format_report

        report = SystemStateReport(
            timestamp="2026-05-24T12:00:00",
            cron_jobs=[],
            failing_cron_jobs=[],
            kanban_tasks=[],
            kanban_gaps=["1 failing job"],
            service_health=ServiceHealth("ok", None, None, None),
            knowledge_page_count=10,
            slack_index_exists=False,
            slack_conversations_count=0,
            improvement_opportunities=["1 failing job"],
        )
        formatted = format_report(report)
        assert "System Intelligence Scan" in formatted
        assert "Improvement Opportunities" in formatted

    def test_save_report(self):
        """Should save report to a timestamped file."""
        import tempfile
        from scanner import save_report

        report = SystemStateReport(
            timestamp="2026-05-24T12:00:00",
            cron_jobs=[],
            failing_cron_jobs=[],
            kanban_tasks=[],
            kanban_gaps=[],
            service_health=ServiceHealth("ok", None, None, None),
            knowledge_page_count=5,
            slack_index_exists=False,
            slack_conversations_count=0,
            improvement_opportunities=[],
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("scanner.os.path.expanduser", return_value=tmpdir):
                path = save_report(report)
                assert path.startswith(tmpdir)
                assert os.path.exists(path)
