# HARNESS.md

# EconCheck

## Purpose

EconCheck is an economic-analysis agent harness designed for answering economics questions using FRED data.

The objective of the project is not to build the most capable economic analyst. The objective is to demonstrate a well-governed agent harness whose behavior is constrained, observable, and correctable.

The harness governs the worker.

The worker proposes actions.

The harness decides whether those actions are allowed, verifies results, routes failures, and determines when work may be released to the user.

---

# Core Philosophy

The worker is responsible for generating plans, selecting data, writing code, and drafting answers.

The harness is responsible for:

- enforcing boundaries
- executing tools
- validating outputs
- generating alarms
- routing retries
- escalating failures
- exposing observability

The worker never directly controls tool execution, release decisions, retries, or escalation.

---

# Four Pillars

The architecture is organized around four pillars.

## 1. Loop

The orchestrator owns execution.

The worker never decides whether a run succeeds.

The orchestrator controls:

- stage progression
- retries
- escalation
- release

The loop is the central control mechanism of the system.

---

## 2. Tools

The worker may request tools.

The harness executes them.

Current tools:

### FRED Search

Searches FRED for economic series.

Purpose:

- discover available data
- identify candidate series

Implementation:

- fredapi

---

### FRED Fetch

Fetches observations for selected series.

Purpose:

- retrieve economic data

Implementation:

- fredapi

---

### Run Analysis Code

Executes worker-generated pandas code.

Purpose:

- perform calculations
- generate tables
- generate charts

Implementation:

- sandboxed subprocess

---

## 3. Guardrails

Guardrails define prohibited actions.

Guardrails evaluate proposals before execution.

Guardrails answer:

> Is the worker allowed to do this?

Examples:

- prompt injection detection
- scope enforcement
- approved tool enforcement
- code safety
- data security

Guardrails do not evaluate correctness.

They evaluate permission.

---

## 4. Observability

Every stage emits artifacts.

Every artifact is visible.

Every retry is visible.

Every alarm is visible.

A user should be able to reconstruct the entire run from observability data.

Observability exists for:

- debugging
- governance
- demonstrations
- auditability

---

# System Architecture

```text
User Prompt
    ↓
Input Guardrails
    ↓
Planning
    ↓
Plan Guardrails
    ↓
Data Discovery
    ↓
Data Checkpoints
    ↓
Code Generation
    ↓
Code Checkpoints
    ↓
Draft Answer
    ↓
Answer Checkpoints
    ↓
Checker Review
    ↓
Release
```

At any stage:

```text
Failure
    ↓
Alarm
    ↓
Retry / Escalate
```

---

# Orchestrator

The orchestrator is the central controller.

Responsibilities:

- maintain state
- execute stages
- run guardrails
- run checkpoints
- create alarms
- route retries
- route escalation
- release answers

The orchestrator owns the loop.

---

# Worker

The worker performs economic reasoning.

The worker is responsible for:

- planning
- selecting data
- writing code
- drafting answers

The worker is not responsible for:

- tool execution
- retries
- escalation
- release decisions

Worker interface:

```python
plan()

select_data()

write_code()

draft_answer()
```

---

# Planner

The planner creates a structured execution plan.

Every plan must contain:

```json
{
  "question_type": "",
  "economic_concepts": [],
  "measurement_strategy": "",
  "information_requirements": [],
  "search_queries": [],
  "required_outputs": [],
  "success_criteria": []
}
```

All fields are required.

Plans that fail schema validation are rejected.

---

# Data Discovery

The worker may not invent data.

Data must be discovered through FRED search.

The worker:

1. Reviews planner requirements
2. Searches FRED
3. Evaluates candidates
4. Selects evidence

The worker must justify selections.

---

# Analysis Code

The worker writes pandas code.

The worker writes real Python.

The harness executes code.

The worker never executes code directly.

The sandbox prohibits:

- network access
- package installation
- arbitrary subprocess creation
- access outside approved directories

---

# Draft Answers

The worker produces a user-facing explanation.

The answer must be grounded in generated metrics and tables.

The worker may not invent values.

---

# Checker

The checker performs independent review.

The checker evaluates:

- plan quality
- data quality
- code quality
- answer quality

The checker may force a retry.

The checker may return execution to:

- planning
- data discovery
- code generation
- draft generation

The checker never releases answers.

---

# Guardrails

Guardrails evaluate proposed actions.

Examples include:

## Input Guardrails

- economic scope
- FRED-answerable scope
- prompt injection
- security violations

## Planning Guardrails

- approved tools only
- valid planner schema
- no out-of-scope sources

## Data Guardrails

- approved FRED access only
- no fabricated series

## Code Guardrails

- sandbox restrictions
- filesystem restrictions
- network restrictions

---

# Checkpoints

Checkpoints evaluate generated artifacts.

Checkpoints answer:

> Is there sufficient evidence to continue?

Examples:

## Data Checkpoints

- provenance
- completeness
- freshness
- information sufficiency

## Code Checkpoints

- execution success
- schema compliance
- math sanity
- chart production

## Answer Checkpoints

- grounding
- success criteria completion

---

# Alarms

Every failure becomes an alarm.

Alarm schema:

```json
{
  "type": "",
  "severity": "",
  "stage": "",
  "message": "",
  "context": {},
  "recommended_action": "",
  "retry_from": ""
}
```

Alarms are the primary routing mechanism.

---

# Retry Logic

Retries are stage-specific.

Examples:

Data failure:

```text
Retry from Data Discovery
```

Code failure:

```text
Retry from Code Generation
```

Checker failure:

```text
Retry from Planning
```

Maximum retries:

```text
max_turns = 5
```

After maximum retries:

```text
Escalate
```

---

# Escalation

The harness must know when to stop.

Examples:

- repeated failure
- unsupported question
- insufficient data
- security concerns

Escalation displays:

- alarm
- failure reason
- suggested next actions

---

# Observability

Every stage writes artifacts.

Examples:

```text
input.json

plan.json

fred_search.json

selected_data.json

generated_code.py

code_output.json

checkpoint_results.json

checker_review.json

final_answer.json
```

Observability must support complete run reconstruction.

---

# Frontend

The application uses Streamlit.

## Chat Page

User-facing experience.

Displays:

- question input
- answer
- chart
- status

---

## Observability Page

Read-only harness inspection.

Displays:

- timeline
- planner output
- tool usage
- selected data
- generated code
- checkpoints
- alarms
- retries
- checker review
- artifacts

The observability page exists to make harness behavior visible.

---

# Acceptance Test

Canonical end-to-end test:

```text
What has happened to CPI inflation over the last five years?
```

Successful execution requires:

1. Valid plan
2. Successful FRED search
3. Correct series selection
4. Successful data validation
5. Successful code execution
6. Chart generation
7. Grounded answer
8. Checker approval
9. Release

Failure at any stage must be observable, explainable, and routable.

---

# Future Work

Not part of the initial build:

- replay/resume
- MCP integration
- OpenAI OAuth
- second worker implementation
- additional data providers
- advanced checker workflows

These features may be added after the core harness is complete.