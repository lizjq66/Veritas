# External integration examples

Veritas is a pre-trade verifier. Any AI-agent framework can call
`POST /verify/proposal` against a running Veritas server with a
`TradeProposal` plus `AccountConstraints` (optionally a `Portfolio`)
and receive back a `Certificate` containing per-gate verdicts, the
attached assumptions, the final approved notional, and a combined
`approves` flag. Callers use the certificate to decide whether to
execute: on `approves=true` they submit the `final_notional_usd` to
their venue, on `approves=false` they route the rejection reasons
back to the operator or a handler.

Veritas does not depend on either framework below. These files live
in `examples/` precisely because they are consumers of a stable,
language-agnostic HTTP contract — the same pattern works from
TypeScript, Rust, or anything that can POST JSON.

Before running either example, start a local Veritas server:

```bash
lake build
pip install -r requirements.txt
python -m python.api.run        # serves on http://localhost:8000
```

Install example-only dependencies:

```bash
pip install -r examples/external_integration/requirements-examples.txt
```

## The two examples

- **[`anthropic_sdk_loop.py`](anthropic_sdk_loop.py)** — an
  Anthropic-SDK one-shot loop: Claude is given a natural-language
  market description, produces a structured trade proposal via
  tool-use, Veritas verifies it, the result is printed. Demonstrates
  the minimum integration surface: *LLM proposes → Veritas verifies
  → caller decides*.

- **[`langgraph_integration.py`](langgraph_integration.py)** — a
  LangGraph state graph with four nodes (intent, proposal generation,
  verification, terminal) that calls Veritas as a `@tool`. Rejected
  certificates route to a dedicated rejection handler node instead of
  the execution node. Demonstrates how the same HTTP contract
  embeds into a graph-shaped agent framework.
