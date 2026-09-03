"""
Report generation: JSON and Markdown formats.
"""

import json
from datetime import datetime
from pathlib import Path

from mobilerun_autotest.models import PENDING_AI, CaseResult


class ReportWriter:
    """
    Incrementally write test reports after each case.

    Generates:
    - report.json - Machine-readable results
    - report.md - Human-readable markdown table
    """

    def __init__(self, report_dir: Path, suite: str):
        self.dir = report_dir
        self.suite = suite
        self.json_path = report_dir / "report.json"
        self.md_path = report_dir / "report.md"
        self.results: list[CaseResult] = []
        self.started = datetime.now()

    def add(self, result: CaseResult) -> None:
        """Add a case result and immediately flush to disk."""
        self.results.append(result)
        self.flush()

    def _summary(self) -> dict:
        """Build summary dict for JSON report."""
        counts: dict[str, int] = {}
        for r in self.results:
            counts[r.status] = counts.get(r.status, 0) + 1

        return {
            "suite": self.suite,
            "started": self.started.isoformat(timespec="seconds"),
            "counts": counts,
            "total": len(self.results),
            "cases": [
                {
                    "id": r.case.id,
                    "title": r.case.title,
                    "status": r.status,
                    "run_exit_code": r.run_exit_code,
                    "seconds": r.run_seconds,
                    "agent_steps": r.agent_steps,
                    "detail": r.detail,
                    "verify": r.verify_results,
                    "ai_judge_images": r.ai_judge_images,
                    "source_file": r.case.source_file,
                    "attempts": r.attempts if r.attempts else None,
                    "pass_rate": r.pass_rate() if r.attempts else None,
                    "trajectory_path": r.trajectory_path,
                }
                for r in self.results
            ],
        }

    def flush(self) -> None:
        """Write reports to disk (JSON and Markdown)."""
        # Write JSON
        self.json_path.write_text(
            json.dumps(self._summary(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        # Write Markdown
        self.md_path.write_text(self._generate_markdown(), encoding="utf-8")

    def _generate_markdown(self) -> str:
        """Generate markdown report content."""
        lines = [
            f"# MobileRun AutoTest Report — {self.suite}",
            "",
            f"- Started: {self.started:%Y-%m-%d %H:%M:%S}",
            f"- Total Cases: {len(self.results)}",
            "",
            "## Summary",
            "",
        ]

        # Count by status
        counts: dict[str, int] = {}
        for r in self.results:
            counts[r.status] = counts.get(r.status, 0) + 1

        for status in ["PASS", "FAIL", "ERROR", "PENDING_AI", "EXPECTED", "SKIPPED"]:
            if status in counts:
                icon = _STATUS_ICON.get(status, "")
                lines.append(f"- {icon} **{status}**: {counts[status]}")

        lines.extend([
            "",
            "## Test Cases",
            "",
            "| Status | ID | Title | Steps | Time(s) | Pass Rate | Detail |",
            "|--------|----|----|-------|---------|-----------|--------|",
        ])

        for r in self.results:
            icon = _STATUS_ICON.get(r.status, "")
            detail = (r.detail or "").replace("|", "\\|")[:150]
            pass_rate = r.pass_rate() or "—"
            steps = f"{r.agent_steps}" if r.agent_steps else "—"

            lines.append(
                f"| {icon} {r.status} "
                f"| `{r.case.id}` "
                f"| {r.case.title} "
                f"| {steps} "
                f"| {r.run_seconds} "
                f"| {pass_rate} "
                f"| {detail} |"
            )

        # AI judgment section
        lines.extend([
            "",
            "## AI Vision Judgment (PENDING_AI)",
            "",
        ])

        pending = [
            (r, v)
            for r in self.results
            for v in r.verify_results
            if v.get("status") == PENDING_AI
        ]

        if not pending:
            lines.append("*(No items awaiting judgment)*")
        else:
            lines.append("| Case ID | Description | Image | AI Verdict | Reason |")
            lines.append("|---------|-------------|-------|------------|--------|")
            for r, v in pending:
                img = v.get("image", "")
                desc = v.get("description", "")
                lines.append(
                    f"| `{r.case.id}` | {desc} | `{img}` | _TODO_ | _TODO_ |"
                )

        # Trajectory links
        lines.extend([
            "",
            "## Trajectories",
            "",
        ])

        trajectories = [(r.case.id, r.trajectory_path) for r in self.results if r.trajectory_path]
        if not trajectories:
            lines.append("*(No trajectories saved)*")
        else:
            for case_id, path in trajectories:
                lines.append(f"- `{case_id}`: `{path}`")

        return "\n".join(lines) + "\n"


_STATUS_ICON = {
    "PASS": "✅",
    "FAIL": "❌",
    "ERROR": "💥",
    "PENDING_AI": "🤖",
    "EXPECTED": "⚠️",
    "SKIPPED": "⏭️",
}
