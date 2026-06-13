# ROADMAP.md

# EconCheck Development Roadmap

## Purpose

This roadmap defines the implementation sequence for EconCheck.

The goal is to maximize the probability of producing a working harness within the hackathon timeline.

Principles:

1. Build vertically.
2. Test before expanding.
3. Finish the loop first.
4. Optimize for demonstrability.
5. Prioritize harness functionality over agent sophistication.

---

# Success Definition

A deployed Streamlit application successfully answers:

```text
What has happened to CPI inflation over the last five years?
```

while exposing:

- loop behavior
- tool usage
- guardrails
- checkpoints
- alarms
- retries
- observability

---

# Development Strategy

Build the smallest complete harness first.

Do not build advanced functionality until the complete loop exists.

Order:

```text
Loop
→ Tools
→ Guardrails
→ Checkpoints
→ Observability
→ UI
→ Refinement
```

---

# NOW

---

# Milestone 0

## Project Initialization

### Tasks

Create repository structure.

Create virtual environment.

Install dependencies.

Create:

```text
app/
harness/
workers/
tests/
runs/
```

Create:

```text
HARNESS.md

TECHNICAL_SPEC.md

ROADMAP.md
```

### Acceptance Criteria

```text
pytest runs

streamlit launches

repository structure exists
```

---

# Milestone 1

## Core State System

### Objective

Create the foundation required for the loop.

### Tasks

Implement:

```python
Stage

RunState

Alarm
```

Implement serialization.

Implement artifact storage.

### Acceptance Criteria

Create a RunState.

Advance stages.

Persist state.

Load state.

---

# Milestone 2

## Orchestrator

### Objective

Build loop control.

### Tasks

Implement:

```python
run()

retry()

escalate()

release()
```

Implement stage routing.

Implement retry counter.

Implement max_turns.

### Acceptance Criteria

Simulated run advances through stages.

Retry routing functions.

Escalation functions.

---

# Milestone 3

## Planner Artifact

### Objective

Implement structured planning.

### Tasks

Create:

```python
PlannerArtifact
```

Implement validation.

Implement serialization.

### Acceptance Criteria

PlannerArtifact validates.

Missing fields fail.

Invalid schema rejected.

---

# Milestone 4

## Worker Interface

### Objective

Implement worker contracts.

### Tasks

Create:

```python
plan()

select_data()

write_code()

draft_answer()
```

Create mock worker.

### Acceptance Criteria

Mock worker completes run.

No real model required.

---

# Milestone 5

## Tool Layer

### Objective

Implement FRED tools.

### Tasks

Install:

```text
fredapi
```

Implement:

```python
fred_search()

fred_fetch()
```

Create wrappers.

### Acceptance Criteria

Search returns results.

Fetch returns observations.

Artifacts persisted.

---

# Milestone 6

## Analysis Runner

### Objective

Execute generated code.

### Tasks

Implement:

```python
run_analysis_code()
```

Subprocess execution.

Sandbox restrictions.

Timeouts.

### Acceptance Criteria

Generated code executes.

Output artifact produced.

Timeout enforced.

---

# Milestone 7

## Input Guardrails

### Objective

Reject invalid requests.

### Tasks

Implement:

```python
EconomicScopeGuardrail

FredAnswerableGuardrail

PromptInjectionGuardrail

DataSecurityGuardrail
```

Create registry.

### Acceptance Criteria

Valid economic question passes.

Prompt injection blocked.

Non-economic question blocked.

---

# Milestone 8

## Planning Guardrails

### Objective

Validate planner output.

### Tasks

Implement:

```python
PlannerSchemaGuardrail

ApprovedToolGuardrail
```

### Acceptance Criteria

Malformed plan blocked.

Unauthorized tool blocked.

---

# Milestone 9

## Data Checkpoints

### Objective

Validate selected evidence.

### Tasks

Implement:

```python
SourceProvenanceCheckpoint

DataCompletenessCheckpoint

FreshnessCheckpoint

InformationSufficiencyCheckpoint
```

### Acceptance Criteria

Invented series fail.

Missing evidence fails.

Expected release lag warns.

---

# Milestone 10

## Code Checkpoints

### Objective

Validate computations.

### Tasks

Implement:

```python
CodeExecutionCheckpoint

OutputShapeCheckpoint

MathSanityCheckpoint

ChartPromiseCheckpoint
```

### Acceptance Criteria

Failed code rejected.

NaN values rejected.

Missing chart rejected.

---

# Milestone 11

## Answer Checkpoints

### Objective

Validate answers.

### Tasks

Implement:

```python
AnswerGroundingCheckpoint

SuccessCriteriaCheckpoint
```

### Acceptance Criteria

Ungrounded claims fail.

Missing success criteria fail.

---

# Milestone 12

## Alarm Routing

### Objective

Convert failures into actions.

### Tasks

Connect:

```python
checkpoint
→
alarm
→
orchestrator
```

Implement:

```python
retry

escalate

abort
```

### Acceptance Criteria

Failures produce alarms.

Alarms route correctly.

---

# Milestone 13

## Checker

### Objective

Implement independent review.

### Tasks

Create:

```python
CheckerArtifact
```

Implement review logic.

Support:

```text
retry_from planning

retry_from data_discovery

retry_from code_generation

retry_from draft_answer
```

### Acceptance Criteria

Checker can force retries.

Checker can send execution back to planning.

---

# Milestone 14

## Observability

### Objective

Make every stage visible.

### Tasks

Persist:

```text
input

plan

search

data

code

analysis

draft

checker

alarms
```

Implement event timeline.

Implement artifact viewer.

### Acceptance Criteria

Entire run reconstructable.

Every stage observable.

---

# Milestone 15

## Streamlit Chat Page

### Objective

Create user interface.

### Tasks

Question input.

Answer display.

Chart display.

Status display.

### Acceptance Criteria

User can submit question.

Answer displayed.

---

# Milestone 16

## Streamlit Observability Page

### Objective

Expose harness internals.

### Tasks

Display:

```text
timeline

planner output

tool usage

selected series

generated code

analysis artifact

checkpoint results

alarms

retry history

checker review
```

### Acceptance Criteria

Run can be inspected end-to-end.

---

# Milestone 17

## End-to-End CPI Test

### Objective

Validate complete harness.

### Test

```text
What has happened to CPI inflation over the last five years?
```

### Required Outcome

Pass input guardrails.

Generate valid plan.

Search FRED.

Select CPI series.

Pass data checkpoints.

Generate code.

Pass code checkpoints.

Generate chart.

Generate answer.

Pass answer checkpoints.

Pass checker review.

Release result.

### Acceptance Criteria

All stages succeed.

Observability complete.

Application deployed.

---

# NEXT

---

# Replay and Resume

Restart from saved stages.

Resume failed runs.

---

# MCP Server

Expose EconCheck as an MCP tool.

Allow Claude integration.

---

# Additional Worker Providers

OpenAI worker.

Anthropic worker.

Provider switching.

---

# Advanced Observability

Failure analytics.

Checkpoint metrics.

Alarm dashboards.

Run comparisons.

---

# Additional Data Sources

BLS.

BEA.

Uploaded datasets.

---

# Advanced Checker

Multiple review passes.

Cross-validation.

Independent model review.

---

# Bonus Demonstration

Swap worker implementation without modifying harness.

Demonstrate portability.

---

# Build Order Summary

```text
Foundation
    ↓
Loop
    ↓
Tools
    ↓
Guardrails
    ↓
Checkpoints
    ↓
Checker
    ↓
Observability
    ↓
UI
    ↓
End-to-End Test
    ↓
Deployment
```

No milestone is considered complete until its acceptance criteria pass.