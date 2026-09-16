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
- OpenAI worker calls use **stage-specific hard timeouts on a daemon thread** and **no SDK retries** (see table below). A whole run also has a 3-minute wall-clock deadline and a stage-loop cap so the UI cannot spin forever. A stage timeout retries that stage **once** if at least 15 seconds remain in the run budget, then escalates. Ctrl+C should stop promptly instead of sitting on Streamlit “Stopping…” while HTTP finishes.
- Subprocess-backed analysis sandbox
- Streamlit chat + observability for real runs under `runs/`
- Mock worker for a reproducible CPI demo, unemployment-style single-series questions, inflation-vs-real-GDP correlation (`CPIAUCSL`+`GDPC1`), and CPI vs PCE inflation comparisons (`CPIAUCSL`+`PCEPI`) when those IDs appear in search results
- Optional OpenAI worker/checker behind the same protocol. Known question classes (canonical CPI, CPI vs PCE, inflation vs GDP) use local analysis/draft templates and a harness chart brief — they do **not** pay for an extra `design_chart` + `write_code` model round-trip. That stacking was exhausting the 3-minute run budget on easy two-series questions. Remaining OpenAI `write_code` prompts require short claim-focused scripts (~80–120 lines, few helpers, follow `chart_brief`, YoY + gap for two price indexes). Oversized generated code fails a simplicity checkpoint and retries from `code_generation` instead of executing.
- Mixed-scale charts: workers emit a structured **chart brief** (`chart_brief.json`) before analysis codegen. Correlation/growth questions plot period-over-period percent growth on a shared percent axis; incompatible raw levels (CPI index vs GDP in billions) use dual y-axes or stacked panels. Harness checkpoints reject dwarf shared-axis overlays and require units plus FRED series ids on multi-series charts.

## Remaining limitations

- The mock worker is a small deterministic specialist, not a general economist. It plans the canonical CPI demo onto `CPIAUCSL`, inflation-vs-real-GDP questions onto `CPIAUCSL`+`GDPC1`, and CPI vs PCE questions onto `CPIAUCSL`+`PCEPI` when those IDs appear in search results. It never invents series IDs.
- OpenAI mode uses local templates for those same known classes (no OpenAI `write_code` / `design_chart` / `draft` call). A CPI vs PCE question is a two-series year-over-year gap, not a CPI-only trend and not a GDP correlation. Canonical CPI fallback remains limited to the exact demo CPI question with CPI-only data. If OpenAI still writes analysis code (unknown question classes), the prompt forbids kitchen-sink stats libraries and a size checkpoint rejects scripts over 300 nonempty lines or 8 helpers before the sandbox runs them. Timeouts are unchanged (write_code 120s, whole-run 180s).
- OpenAI calls use stage-specific hard timeouts (SDK retries disabled; wait happens off the Streamlit script thread). Constants live in `workers/openai_client.py` (`OPENAI_TIMEOUT_SECONDS_BY_STAGE` / `OPENAI_TIMEOUT_SECONDS_BY_SCHEMA`):

  | Stage | Schema | Timeout |
  | --- | --- | --- |
  | plan | `planner_artifact` | 30s |
  | select_data | `data_selection_artifact` | 30s |
  | design_chart | `chart_brief_artifact` | 60s |
  | write_code | `code_artifact` | 120s |
  | draft_answer | `draft_artifact` | 30s |
  | checker review | `checker_artifact` | 30s |

  Each remaining OpenAI call is capped by remaining run budget so a retry cannot wait past the 3-minute deadline. Chart design is harness-local (the 60s `design_chart` budget applies only if a future caller opts into a model brief). Known two-series questions skip `write_code` entirely. A live OpenAI run should finish or escalate within about three minutes. If a remaining model stage times out, you should see a `stage_timeout` alarm in plain language and one retry when time remains. Ctrl+C persists a `run_interrupted` alarm and re-raises so “Stopping…” does not wait on a blocking HTTP call.
- Mixed-frequency relationship analysis aligns series by carrying higher-frequency values forward onto lower-frequency dates and reports contemporaneous growth-rate correlation, not a causal or full lead-lag model. CPI vs PCE uses year-over-year percent changes on a shared percent axis (index bases differ). Observability shows `chart_brief.json` next to analysis artifacts.
- Data is FRED-only. Forecasting, policy advice, and non-economic questions are rejected.
- Replay/resume from an arbitrary checkpoint, MCP, and extra data providers are out of scope.
- There is no Vercel frontend; deploy the Streamlit app (Community Cloud, a VM, or any host that can run `streamlit run app.py`).

## Repository map

```text
app/chat.py                 Streamlit chat entrypoint
app/observability.py        Live run artifact viewer
pages/2_Observability.py    Streamlit multipage wrapper
harness/orchestrator.py     State machine, guardrails, checkpoints, release
harness/charts.py           Mixed-scale chart layout + Streamlit rendering
harness/tools/fred.py       Live FRED search/fetch
harness/tools/code_runner.py
harness/config.py           Env / secrets resolution
workers/mock_worker.py      Deterministic worker
workers/openai_worker.py    Optional model-backed worker
workers/chart_briefs.py     Adaptive chart-brief builder + design advice
```
