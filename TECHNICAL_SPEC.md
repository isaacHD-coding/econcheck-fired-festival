# TECHNICAL_SPEC.md

# EconCheck Technical Specification

## Purpose

This document defines the implementation contracts for EconCheck.

Unlike HARNESS.md, which explains architecture and intent, this document defines:

- repository structure
- interfaces
- schemas
- data contracts
- state transitions
- acceptance requirements

Implementation must conform to this document.

---

# Repository Structure

```text
econcheck/

├── app/
│   ├── chat.py
│   └── observability.py
│
├── harness/
│   ├── orchestrator.py
│   ├── state.py
│   ├── alarms.py
│   │
│   ├── guardrails/
│   ├── checkpoints/
│   ├── tools/
│   ├── persistence/
│   └── observability/
│
├── workers/
│   ├── base.py
│   └── llm_worker.py
│
├── tests/
│
├── runs/
│
├── HARNESS.md
├── TECHNICAL_SPEC.md
└── ROADMAP.md
```

---

# State Model

## Stage Enum

```python
class Stage(Enum):
    INPUT
    PLANNING
    DATA_DISCOVERY
    CODE_GENERATION
    DRAFT_ANSWER
    CHECKER_REVIEW
    RELEASED
    ESCALATED
```

---

## RunState

```python
@dataclass
class RunState:
    run_id: str
    question: str
    current_stage: Stage
    retry_count: int
    max_turns: int = 5
    artifacts: dict
    alarms: list
```

---

# Worker Interface

```python
class Worker(Protocol):

    def plan(
        self,
        question: str,
        state: RunState
    ) -> PlannerArtifact:
        ...

    def select_data(
        self,
        plan: PlannerArtifact,
        search_results: list
    ) -> DataSelectionArtifact:
        ...

    def write_code(
        self,
        plan: PlannerArtifact,
        data_summary: DataArtifact
    ) -> CodeArtifact:
        ...

    def draft_answer(
        self,
        plan: PlannerArtifact,
        analysis: AnalysisArtifact
    ) -> DraftArtifact:
        ...
```

---

# Planner Artifact

All fields required.

```python
@dataclass
class PlannerArtifact:

    question_type: str

    economic_concepts: list[str]

    measurement_strategy: str

    information_requirements: list[str]

    search_queries: list[str]

    required_outputs: list[str]

    success_criteria: list[str]
```

Validation failure blocks execution.

---

# Data Selection Artifact

```python
@dataclass
class DataSelectionArtifact:

    selected_series: list[dict]

    rejected_series: list[dict]

    justification: str
```

Example:

```json
{
  "selected_series": [
    {
      "series_id": "CPIAUCSL",
      "reason": "Primary CPI series"
    }
  ]
}
```

---

# Tool Contracts

## Tool: FRED Search

Input:

```python
search_text: str
```

Output:

```python
list[SeriesSearchResult]
```

Schema:

```python
@dataclass
class SeriesSearchResult:

    series_id: str

    title: str

    frequency: str

    units: str

    observation_start: str

    observation_end: str
```

---

## Tool: FRED Fetch

Input:

```python
list[str]
```

Output:

```python
DataArtifact
```

---

## Data Artifact

```python
@dataclass
class DataArtifact:

    series_ids: list[str]

    observations: dict

    metadata: dict
```

---

## Tool: Run Analysis Code

Input:

```python
CodeArtifact
DataArtifact
```

Output:

```python
AnalysisArtifact
```

---

# Code Artifact

```python
@dataclass
class CodeArtifact:

    code: str
```

Worker writes complete Python.

---

# Analysis Artifact

Structured output only.

No free-form text.

```python
@dataclass
class AnalysisArtifact:

    tables: list

    metrics: list

    claims: list

    charts: list

    method_notes: str

    warnings: list
```

---

# Metric Schema

```python
{
  "name": "",
  "value": 0,
  "unit": "",
  "source_series": []
}
```

---

# Claim Schema

```python
{
  "text": "",
  "metric_refs": []
}
```

Claims must reference metrics.

---

# Draft Artifact

```python
@dataclass
class DraftArtifact:

    answer: str

    referenced_metrics: list[str]

    chart_paths: list[str]
```

---

# Checker Artifact

```python
@dataclass
class CheckerArtifact:

    passed: bool

    issues: list[str]

    retry_from: str

    explanation: str
```

retry_from values:

```text
planning

data_discovery

code_generation

draft_answer
```

---

# Guardrails

Guardrails run before execution.

---

## Guardrail Result

```python
@dataclass
class GuardrailResult:

    passed: bool

    reason: str
```

---

## Initial Registry

### Input

```python
EconomicScopeGuardrail

FredAnswerableGuardrail

PromptInjectionGuardrail

DataSecurityGuardrail
```

### Planning

```python
ApprovedToolGuardrail

PlannerSchemaGuardrail
```

### Code

```python
CodeSafetyGuardrail
```

---

# Checkpoints

Checkpoints evaluate artifacts.

Failures become alarms.

---

## Checkpoint Result

```python
@dataclass
class CheckpointResult:

    passed: bool

    alarm: Alarm | None
```

---

## Data Checkpoints

```python
SourceProvenanceCheckpoint

DataCompletenessCheckpoint

FreshnessCheckpoint

InformationSufficiencyCheckpoint
```

---

## Code Checkpoints

```python
CodeExecutionCheckpoint

OutputShapeCheckpoint

MathSanityCheckpoint

ChartPromiseCheckpoint
```

---

## Answer Checkpoints

```python
AnswerGroundingCheckpoint

SuccessCriteriaCheckpoint
```

---

# Alarm Schema

Every failure generates an alarm.

```python
@dataclass
class Alarm:

    type: str

    severity: str

    stage: str

    message: str

    context: dict

    recommended_action: str

    retry_from: str
```

---

# Alarm Actions

Allowed values:

```text
retry

escalate

abort
```

---

# Orchestrator Flow

```text
INPUT
↓
PLANNING
↓
DATA_DISCOVERY
↓
CODE_GENERATION
↓
DRAFT_ANSWER
↓
CHECKER_REVIEW
↓
RELEASED
```

---

# Retry Routing

If alarm:

```python
recommended_action == retry
```

then:

```python
retry_from
```

determines stage.

Examples:

```text
planning

data_discovery

code_generation

draft_answer
```

---

# Escalation

Conditions:

```text
retry_count >= 5

unsupported question

critical failure
```

Result:

```python
Stage.ESCALATED
```

---

# Persistence

Each stage writes artifacts.

Directory:

```text
runs/{run_id}/
```

Files:

```text
input.json

plan.json

fred_search.json

selected_data.json

generated_code.py

analysis.json

draft.json

checker.json

alarms.json
```

---

# Observability

Each stage emits:

```python
timestamp

stage

artifact_type

artifact_path
```

Observable events:

```text
guardrail_pass

guardrail_fail

checkpoint_pass

checkpoint_fail

alarm

retry

release

escalation
```

---

# Streamlit

## Page 1

Chat

Displays:

```text
question

answer

chart

status
```

---

## Page 2

Observability

Displays:

```text
timeline

planner artifact

tool calls

selected data

generated code

analysis output

checkpoint results

alarms

retry history

checker review
```

Read-only.

---

# End-to-End Acceptance Test

Input:

```text
What has happened to CPI inflation over the last five years?
```

Expected:

```text
valid plan

valid data discovery

successful code execution

chart generated

grounded answer

checker approval

release
```

Failure at any stage must be observable and routable.