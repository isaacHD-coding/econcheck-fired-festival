"""Checkpoint registry for the EconCheck harness."""

from harness.checkpoints.answer import (
    AnswerGroundingCheckpoint,
    SuccessCriteriaCheckpoint,
)
from harness.checkpoints.base import CheckpointResult
from harness.checkpoints.code import (
    ChartPromiseCheckpoint,
    CodeExecutionCheckpoint,
    MathSanityCheckpoint,
    OutputShapeCheckpoint,
)
from harness.checkpoints.data import (
    DataCompletenessCheckpoint,
    FreshnessCheckpoint,
    InformationSufficiencyCheckpoint,
    SourceProvenanceCheckpoint,
)


DATA_CHECKPOINTS = (
    SourceProvenanceCheckpoint(),
    DataCompletenessCheckpoint(),
    FreshnessCheckpoint(),
    InformationSufficiencyCheckpoint(),
)

CODE_CHECKPOINTS = (
    CodeExecutionCheckpoint(),
    OutputShapeCheckpoint(),
    MathSanityCheckpoint(),
    ChartPromiseCheckpoint(),
)

ANSWER_CHECKPOINTS = (
    AnswerGroundingCheckpoint(),
    SuccessCriteriaCheckpoint(),
)

CHECKPOINT_REGISTRY = {
    "data": DATA_CHECKPOINTS,
    "code": CODE_CHECKPOINTS,
    "answer": ANSWER_CHECKPOINTS,
}


__all__ = [
    "ANSWER_CHECKPOINTS",
    "CHECKPOINT_REGISTRY",
    "CODE_CHECKPOINTS",
    "AnswerGroundingCheckpoint",
    "ChartPromiseCheckpoint",
    "CheckpointResult",
    "CodeExecutionCheckpoint",
    "DATA_CHECKPOINTS",
    "DataCompletenessCheckpoint",
    "FreshnessCheckpoint",
    "InformationSufficiencyCheckpoint",
    "MathSanityCheckpoint",
    "OutputShapeCheckpoint",
    "SourceProvenanceCheckpoint",
    "SuccessCriteriaCheckpoint",
]
