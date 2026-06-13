# AGENT.md

## Purpose

You are building EconCheck, an economic-analysis agent harness.

Before making any changes, read the following files in this order:

1. HARNESS.md
2. TECHNICAL_SPEC.md
3. ROADMAP.md

These documents are the source of truth.

If implementation details conflict with these documents, follow the documents.

Do not invent architecture.

Do not significantly modify architecture without explicit approval.

---

# Development Philosophy

The goal is not to build the smartest economic analyst.

The goal is to build a governed harness that demonstrates:

1. Loop
2. Tools
3. Guardrails
4. Observability

The harness is more important than the worker.

Favor simplicity, observability, and correctness over sophistication.

---

# Architecture Rules

The orchestrator owns execution.

The worker does not:

- execute tools
- route retries
- escalate failures
- release answers

The worker only:

- plans
- selects data
- writes code
- drafts answers

All tool execution occurs through the harness.

---

# Development Process

Implement ROADMAP.md milestones in order.

Do not skip ahead.

Do not begin a milestone until acceptance criteria for the previous milestone are satisfied.

Prefer small commits.

Prefer small pull requests.

---

# Testing Requirements

Use test-driven development whenever practical.

Before implementing a major component:

1. Write the acceptance test.
2. Implement the minimum code required to pass.

The canonical end-to-end test is:

"What has happened to CPI inflation over the last five years?"

This test should remain runnable throughout development.

---

# Implementation Priorities

Priority order:

1. Loop
2. Tools
3. Guardrails
4. Checkpoints
5. Checker
6. Observability
7. UI

Do not optimize UI before the harness works.

---

# Scope Constraints

Current data source:

- FRED only

Current tools:

- FRED Search
- FRED Fetch
- Run Analysis Code

Do not add:

- BLS
- BEA
- MCP
- OAuth
- Additional providers

unless explicitly instructed.

These belong to future milestones.

---

# When Unsure

If multiple implementation choices are possible:

1. Choose the simpler option.
2. Choose the more observable option.
3. Choose the option that better aligns with HARNESS.md.

When uncertainty remains, stop and ask.