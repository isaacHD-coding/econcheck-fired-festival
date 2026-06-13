# EconCheck

EconCheck is a governed economic-analysis agent harness built for the Gauntlet AI 24-hour harness build challenge. It answers economics questions with FRED data while making the harness, not the worker, responsible for control flow, tool execution, validation, alarms, retry routing, persistence, and release decisions.

The current demo question is:

```text
What has happened to CPI inflation over the last five years?
```

That question is intentionally narrow. The goal of this project is not to build the broadest possible economic analyst. The goal is to demonstrate a harness that constrains an agent, records the material it handles, checks intermediate outputs, and makes failures visible.

## What This Builds

EconCheck runs an agent-style worker inside a harness:

```text
User question
  -> harness-owned state machine
  -> worker plan
  -> harness-owned FRED search/fetch
  -> worker-generated analysis code
  -> harness-owned code execution sandbox
  -> explicit checkpoints
  -> checker review
  -> released answer or structured alarm
```

The worker proposes what to do. The harness decides what is allowed, performs the external calls, executes the generated code, validates the artifacts, persists the run, and decides whether an answer can be released.

For the hackathon slice, the committed worker and checker are deterministic mock implementations. That keeps the demo reproducible and makes the harness contract easy to inspect. I am also working toward an LLM-backed worker for the final submission; if it lands, it should plug in behind the same `Worker` protocol without changing the harness interface.

## Why I Built It This Way

I chose economics and FRED because the domain has a clean governance problem: economic answers should be grounded in known data series, with visible provenance and reproducible calculations. A normal chatbot can easily mix reasoning, retrieval, computation, and final prose in one opaque step. EconCheck separates those responsibilities.

Key build decisions:

- Harness first, worker second: the core evaluation target is the harness, so the orchestrator owns stage progression, retry routing, escalation, and release.
- FRED-only data scope: the initial tool surface is intentionally small, which makes provenance and scope enforcement easier to demonstrate.
- Structured artifacts everywhere: plans, data selections, fetched observations, generated code, analysis output, checkpoint results, checker output, final answers, alarms, and state are written under `runs/{run_id}/`.
- Deterministic worker for the baseline demo: the worker behaves through the same protocol a model worker would use, but avoids live model variability during a short judging walkthrough. The intended next upgrade is an LLM-backed worker using the same interface.
- Generated code is still real code: the worker emits Python, and the harness executes it in a subprocess-backed sandbox instead of trusting the worker's computed answer directly.

## Hackathon Requirement Mapping

### 1. Guardrails

Guardrails are declared in the docs and enforced at harness control points rather than hidden inside the worker.

Implemented guardrail behavior includes:

- Worker isolation: the worker cannot call FRED, execute tools, route retries, escalate failures, or release answers.
- Planner schema validation: `PlannerArtifact` requires all planning fields and rejects missing or malformed fields.
- Approved tool surface: the integrated run path only uses harness-owned FRED search, FRED fetch, and analysis-code execution.
- FRED-only data access: selected data must come from live FRED search results before the harness fetches observations.
- Code sandboxing: generated analysis code runs in a temporary subprocess with network calls, subprocess creation, directory changes, and out-of-sandbox file access blocked.

Relevant files:

- `harness/orchestrator.py`
- `harness/tools/fred.py`
- `harness/tools/code_runner.py`
- `workers/artifacts.py`

### 2. Checkpoints

Checkpoints have explicit pass/fail criteria and are persisted to `checkpoint_results.json`.

Implemented checkpoints:

- `SourceProvenanceCheckpoint`: selected series must come from live FRED search results.
- `DataCompletenessCheckpoint`: selected series must include enough numeric observations for the CPI analysis.
- `FreshnessCheckpoint`: latest observations must be within a normal release-lag window.
- `InformationSufficiencyCheckpoint`: CPIAUCSL data must be available for the canonical CPI question.
- `CodeExecutionCheckpoint`: generated code must execute and return a structured analysis artifact.
- `OutputShapeCheckpoint`: analysis output must have the required table, metric, claim, chart, notes, and warning fields.
- `MathSanityCheckpoint`: numeric metrics must be finite and plausibly scaled.
- `ChartPromiseCheckpoint`: analysis must include chart descriptor data.
- `AnswerGroundingCheckpoint`: the draft answer must reference generated metric names.
- `SuccessCriteriaCheckpoint`: the draft answer must satisfy the worker's plan-level success criteria.

### 3. Material Handling

Every run is reconstructable from files in `runs/{run_id}/`.

The integrated CPI path writes:

- `input.json`
- `plan.json`
- `fred_search.json`
- `selected_data.json`
- `data.json`
- `generated_code.py`
- `code_output.json`
- `analysis.json`
- `checkpoint_results.json`
- `draft.json`
- `checker.json`
- `final_answer.json`
- `alarms.json`
- `state.json`

This is the material boundary of the harness: each stage receives structured material, emits structured material, and leaves an audit trail.

### 4. Alarms

Failures become structured alarms using the `Alarm` schema:

```json
{
  "type": "checkpoint_failed",
  "severity": "error",
  "stage": "data_discovery",
  "message": "data_discovery checkpoint failed.",
  "context": {},
  "recommended_action": "retry",
  "retry_from": "data_discovery"
}
```

Alarms are persisted to `alarms.json` and routed by the orchestrator. Retry targets are explicit: `planning`, `data_discovery`, `code_generation`, or `draft_answer`. If retry limits are exceeded, the orchestrator escalates instead of guessing.

## Repository Structure

```text
app/
  chat.py                 Streamlit chat/demo entrypoint
  observability.py        Run artifact loader and Streamlit artifact viewer

harness/
  orchestrator.py         State machine, integrated run loop, checkpoints, release
  state.py                Stage enum and RunState model
  alarms.py               Structured alarm model
  persistence/            JSON and text artifact persistence
  tools/
    fred.py               Harness-owned live FRED search/fetch tools
    code_runner.py        Subprocess-backed generated-code runner

workers/
  base.py                 Swappable Worker protocol
  mock_worker.py          Deterministic CPI worker for demo and tests
  mock_checker.py         Deterministic checker for the integrated demo path
  artifacts.py            Typed artifact schemas and validation

tests/
  test_cpi_e2e.py         Live FRED end-to-end acceptance test
  test_*.py               Unit tests for state, alarms, artifacts, persistence, tools, and worker contracts
```

## External Calls Made

EconCheck does not let the worker make external calls directly. The harness owns all calls.

Live FRED calls:

- `GET https://api.stlouisfed.org/fred/series/search`
  - Used by `fred_search()`
  - Searches for candidate economic series from the worker's plan.
- `GET https://api.stlouisfed.org/fred/series/observations`
  - Used by `fred_fetch()`
  - Fetches observations for selected FRED series such as `CPIAUCSL`.

Required environment variable:

```bash
export FRED_API_KEY="your-fred-api-key"
```

Model/API calls:

- The current demo worker is deterministic and does not call an LLM provider.
- The harness is designed so a future LLM-backed worker can implement the same `Worker` protocol without changing the orchestrator contract.

## How To Run

### Deployed app

The final submission will include a deployed Streamlit URL:

```text
Streamlit URL: <add deployed URL here>
```

The local instructions below are for reviewers who want to run the repository directly.

### 1. Create and activate a virtual environment

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
```

### 2. Configure FRED

The live CPI demo and `tests/test_cpi_e2e.py` require a FRED API key.

```bash
export FRED_API_KEY="your-fred-api-key"
```

### 3. Run tests

Run unit and non-live integration tests:

```bash
python -m pytest -q --ignore=tests/test_cpi_e2e.py
```

Run the full suite, including the live FRED CPI test:

```bash
python -m pytest -q
```

Current local verification without `FRED_API_KEY`:

```text
44 passed, 17 subtests passed
```

The full suite currently fails without `FRED_API_KEY` because the CPI e2e test intentionally requires live FRED integration.

### 4. Run the Streamlit chat app

```bash
streamlit run app/chat.py
```

Submit the default CPI question. The app will create a run under `runs/{run_id}/` and display the released answer if the harness reaches the release stage.

### 5. Inspect observability

```bash
streamlit run app/observability.py
```

Select a run ID to inspect the persisted state, artifacts, checkpoint results, generated code, FRED payloads, alarms, checker result, and final answer.

## Demo Walkthrough

A good 2-3 minute demo flow:

1. Open with the harness purpose: EconCheck is not a general chatbot; it is a governed harness for economic analysis.
2. Show `HARNESS.md` and the four pillars: guardrails, checkpoints, material handling, and alarms.
3. Run the Streamlit chat app with the default CPI question.
4. Show the released answer.
5. Open the observability page and inspect the run artifacts:
   - `plan.json`
   - `fred_search.json`
   - `selected_data.json`
   - `generated_code.py`
   - `analysis.json`
   - `checkpoint_results.json`
   - `final_answer.json`
6. Point out that the worker did not fetch FRED data or execute code. The harness did.
7. Point out that if a checkpoint fails, the harness emits a structured alarm with context and a retry target.

Short framing line for judges:

```text
EconCheck demonstrates that an agent can propose economic analysis, but the harness controls whether the proposal is allowed, what data is fetched, how code is executed, whether outputs pass checks, and whether an answer is released.
```

## What Is Complete

- Core run state and stage model
- Structured alarm schema
- Orchestrator-controlled stage progression
- Retry, release, and escalation primitives
- Swappable worker protocol
- Deterministic CPI worker
- Deterministic checker
- Live FRED search and fetch tools
- Subprocess-backed generated-code runner
- JSON/text artifact persistence
- Integrated CPI demo path
- Observability artifact loader and Streamlit viewer
- Unit tests for state, alarms, artifacts, persistence, worker contracts, orchestrator behavior, and code execution
- Live FRED e2e acceptance test for the CPI question

## Known Limits

- The demo worker is deterministic, not model-backed.
- The data source is intentionally limited to FRED.
- The UI is functional and minimal; the project prioritizes harness behavior over polish.
- Checkpoint and guardrail logic is implemented for the CPI/FRED vertical slice rather than a broad economics domain.
- Replay from an arbitrary checkpoint is documented as a future direction, but the current implementation focuses on complete run reconstruction.

## Final Submission Notes

The project should be presented as a FRED economic-analysis harness, with CPI inflation as the canonical demo question. The deployed Streamlit URL should be added above once it is available.

Worker status: the current repository has a deterministic worker for a reliable baseline demo. The intended final direction is to add an LLM-backed worker if time permits, but the README does not claim that worker exists until it is implemented.
