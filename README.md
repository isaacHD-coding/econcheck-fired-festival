# EconCheck

EconCheck is a governed economic-analysis harness. It answers FRED-answerable economics questions while making the harness—not the worker—responsible for control flow, tool execution, validation, alarms, retry routing, persistence, and release.

The canonical demo question is:

```text
What has happened to CPI inflation over the last five years?
```

The project is a **Streamlit app**, not a Vercel app. The earlier `econcheck-fired-festival.vercel.app` URL is not part of this architecture.

## What it does

```text
User question
  -> input guardrails
  -> harness-owned state machine
  -> worker plan
  -> planning guardrails
  -> harness-owned FRED search/fetch
  -> worker-generated analysis code
  -> harness-owned sandbox execution
  -> checkpoints
  -> checker review
  -> released answer or structured alarm
```

The worker proposes what to do. The harness decides what is allowed, performs FRED calls, executes generated code, validates artifacts, persists the run under `runs/{run_id}/`, and decides whether an answer can be released.

Two worker modes:

- **Mock demo** — deterministic worker/checker. Best for the CPI walkthrough and for FRED series that appear in search results (the mock selects from live search; it does not invent series IDs).
- **OpenAI agent** — model-backed worker/checker behind the same `Worker` protocol. Optional. Requires `OPENAI_API_KEY`.

## Setup

Requires Python 3.11+.

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
```

### Environment variables

Copy `.env.example` to `.env` and fill in your own keys. **Do not commit `.env` or real credentials.**

```bash
cp .env.example .env
```

| Variable | Required | Purpose |
| --- | --- | --- |
| `FRED_API_KEY` | Yes for live FRED | St. Louis Fed API key. Request one at https://fred.stlouisfed.org/docs/api/api_key.html |
| `OPENAI_API_KEY` | Only for OpenAI worker mode | Model-backed planner, code writer, drafter, and checker |

Keys are resolved in this order: sidebar field (if filled) → process environment → `.env` → Streamlit secrets. They are never written into run artifacts.

For Streamlit Community Cloud, add the same names under **App settings → Secrets**:

```toml
FRED_API_KEY = "your-fred-api-key"
# OPENAI_API_KEY = "your-openai-api-key"
```

## Run locally

```bash
streamlit run app.py
```

That starts the chat page. A second **Observability** page lists persisted runs.

1. Confirm a FRED key is loaded (sidebar caption or paste it into the password field).
2. Keep the default CPI question, or ask another FRED-answerable economics question.
3. Click **Run through harness**. OpenAI mode prints each stage into the status box; a run should release or escalate (it will not spin forever). Use the sidebar **Observability** page link (not a full page reload) if you want to inspect artifacts without losing chat state.
4. Inspect the released answer, chart, alarms, and run artifacts.
5. Open Observability and come back to chat: the current run id, question, worker mode, and last results should still be there.

### Tests

Unit and mocked integration tests (no live API keys required):

```bash
python -m pytest -q --ignore=tests/test_cpi_e2e.py --ignore=tests/test_real_agent_e2e.py
```

Full suite, including live FRED (and OpenAI, if configured):

```bash
python -m pytest -q
```

Live tests **skip** when the matching API key is unset. They do not fail the suite.

## What works

- Live FRED search (`fred/series/search`) and fetch (`fred/series/observations`) owned by the harness
- Direct series-id lookup when search text contains an explicit FRED id such as `CPIAUCSL`
- Input guardrails: economic scope, FRED-answerable questions, prompt injection, basic data-security checks
- Planning guardrails: planner schema and approved tools
- Data, code, and answer checkpoints, including provenance (no invented series)
- Alarm routing with retry from `planning`, `data_discovery`, `code_generation`, or `draft_answer`, then escalation after `max_turns`
- OpenAI worker calls use a **30s hard timeout on a daemon thread** and **no SDK retries**. A whole run also has a 3-minute wall-clock deadline and a stage-loop cap so the UI cannot spin forever. Ctrl+C should stop promptly instead of sitting on Streamlit “Stopping…” while HTTP finishes.
- Subprocess-backed analysis sandbox
- Streamlit chat + observability for real runs under `runs/`
- Mock worker for a reproducible CPI demo, unemployment-style single-series questions, and inflation-vs-real-GDP correlation when FRED search returns both `CPIAUCSL` and `GDPC1`
- Optional OpenAI worker/checker behind the same protocol. Canonical CPI analysis/draft fallback is limited to the exact demo CPI question with CPI-only data; multi-series plans keep their relationship analysis.

## Remaining limitations

- The mock worker is a small deterministic specialist, not a general economist. It plans the canonical CPI demo onto `CPIAUCSL`, inflation-vs-real-GDP questions onto `CPIAUCSL`+`GDPC1` when those IDs appear in search results, and otherwise uses live search hits. It never invents series IDs.
- OpenAI mode keeps a canonical CPI analysis/draft fallback only for the exact demo CPI question when the fetched data is CPI-only. Questions about correlation, GDP, or multiple series do not get that canned CPI paragraph.
- OpenAI calls are capped at 30 seconds each (SDK retries disabled, wait happens off the Streamlit script thread). A live OpenAI run should finish or escalate within about three minutes; if the model is slow you may see a `run_deadline_exceeded` or OpenAI timeout alarm instead of a hang. Ctrl+C persists a `run_interrupted` alarm and re-raises so “Stopping…” does not wait on a blocking HTTP call.
- Mixed-frequency relationship analysis aligns series by carrying higher-frequency values forward onto lower-frequency dates and reports contemporaneous growth-rate correlation, not a causal or full lead-lag model.
- Data is FRED-only. Forecasting, policy advice, and non-economic questions are rejected.
- Replay/resume from an arbitrary checkpoint, MCP, and extra data providers are out of scope.
- There is no Vercel frontend; deploy the Streamlit app (Community Cloud, a VM, or any host that can run `streamlit run app.py`).

## Repository map

```text
app/chat.py                 Streamlit chat entrypoint
app/observability.py        Live run artifact viewer
pages/2_Observability.py    Streamlit multipage wrapper
harness/orchestrator.py     State machine, guardrails, checkpoints, release
harness/tools/fred.py       Live FRED search/fetch
harness/tools/code_runner.py
harness/config.py           Env / secrets resolution
workers/mock_worker.py      Deterministic worker
workers/openai_worker.py    Optional model-backed worker
```
