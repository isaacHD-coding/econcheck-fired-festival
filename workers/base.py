"""Worker protocol for EconCheck worker implementations."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from harness.state import RunState
from workers.artifacts import (
    AnalysisArtifact,
    CodeArtifact,
    DataSelectionArtifact,
    DraftArtifact,
    PlannerArtifact,
)


@runtime_checkable
class Worker(Protocol):
    def plan(
        self,
        question: str,
        state: RunState,
    ) -> PlannerArtifact:
        ...

    def select_data(
        self,
        plan: PlannerArtifact,
        search_results: list,
    ) -> DataSelectionArtifact:
        ...

    def write_code(
        self,
        plan: PlannerArtifact,
        data_summary: "DataArtifact",
    ) -> CodeArtifact:
        ...

    def draft_answer(
        self,
        plan: PlannerArtifact,
        analysis: AnalysisArtifact,
    ) -> DraftArtifact:
        ...
