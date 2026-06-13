"""Deterministic mock checker for Milestone 17 integration."""

from __future__ import annotations

from harness.state import RunState
from workers.artifacts import (
    AnalysisArtifact,
    CheckerArtifact,
    DataArtifact,
    DraftArtifact,
    PlannerArtifact,
)


class MockChecker:
    def review(
        self,
        state: RunState,
        plan: PlannerArtifact,
        data: DataArtifact,
        analysis: AnalysisArtifact,
        draft: DraftArtifact,
    ) -> CheckerArtifact:
        return CheckerArtifact(
            passed=True,
            issues=[],
            retry_from="",
            explanation="Mock checker passed.",
        )
