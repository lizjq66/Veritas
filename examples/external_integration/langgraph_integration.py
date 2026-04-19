"""
This file demonstrates how an external agent framework integrates
with Veritas. Veritas itself does not depend on this code.

Pattern: a four-node LangGraph agent calls Veritas as a @tool and
routes based on the returned verdict.

    [intent] → [propose] → [verify-via-veritas] ─┬── approves → [execute]
                                                 └── rejects  → [rejected]

The verify step is a LangChain @tool that POSTs to
http://localhost:8000/verify/proposal. The graph's conditional edge
inspects the certificate's `approves` flag: approvals route to the
execution node, rejections route to a dedicated rejection handler
that surfaces the concatenated reason codes. The execution node never
runs if any gate rejected — that is the whole point of Veritas.

Prerequisites:
    pip install -r examples/external_integration/requirements-examples.txt
    python -m python.api.run        # starts Veritas on http://localhost:8000

Run:
    python examples/external_integration/langgraph_integration.py
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import TypedDict

from langchain_core.tools import tool
from langgraph.graph import END, StateGraph

VERITAS_URL = os.environ.get("VERITAS_URL", "http://localhost:8000")


class AgentState(TypedDict, total=False):
    """Minimal state the graph carries between nodes."""
    intent:      str
    proposal:    dict
    certificate: dict
    decision:    str


@tool
def verify_with_veritas(proposal: dict, equity: float = 10_000.0) -> dict:
    """Submit a trade proposal to Veritas and return the certificate.

    The proposal dict must have `direction`, `notional_usd`,
    `funding_rate`, `price`. Returns Veritas's full Certificate
    (gate1/gate2/gate3 verdicts, assumptions, final_notional_usd,
    approves).
    """
    body = json.dumps({
        "proposal": proposal,
        "constraints": {
            "equity": equity,
            "reliability": 0.8,
            "sample_size": 20,
        },
    }).encode()
    req = urllib.request.Request(
        f"{VERITAS_URL}/verify/proposal",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except urllib.error.URLError as e:
        return {"error": str(e), "approves": False,
                "gate1": {"verdict": "reject", "reason_codes": ["veritas_unreachable"]},
                "gate2": {"verdict": "reject", "reason_codes": ["upstream_gate_rejected"]},
                "gate3": {"verdict": "reject", "reason_codes": ["upstream_gate_rejected"]}}


# ── Nodes ─────────────────────────────────────────────────────────

def intent_node(state: AgentState) -> AgentState:
    """Pass-through: the graph is given an intent; this node records it."""
    return {"intent": state["intent"]}


def propose_node(state: AgentState) -> AgentState:
    """Translate intent into a TradeProposal. A real agent would call an
    LLM here; for demo determinism we key off a keyword in the intent."""
    intent = state["intent"].lower()
    if "positive funding" in intent or "go long" in intent:
        proposal = {"direction": "LONG", "notional_usd": 1500.0,
                    "funding_rate": 0.0012, "price": 68000.0}
    elif "negative funding" in intent or "go short" in intent:
        proposal = {"direction": "SHORT", "notional_usd": 1500.0,
                    "funding_rate": -0.0008, "price": 68000.0}
    else:
        # ambiguous intent → Veritas will catch the direction mismatch
        proposal = {"direction": "LONG", "notional_usd": 1500.0,
                    "funding_rate": -0.0008, "price": 68000.0}
    return {"proposal": proposal}


def verify_node(state: AgentState) -> AgentState:
    cert = verify_with_veritas.invoke({"proposal": state["proposal"]})
    return {"certificate": cert}


def execute_node(state: AgentState) -> AgentState:
    cert = state["certificate"]
    size = cert.get("final_notional_usd", 0.0)
    direction = state["proposal"]["direction"]
    return {"decision": f"EXECUTE {direction} ${size:,.0f}"}


def rejected_node(state: AgentState) -> AgentState:
    cert = state["certificate"]
    reasons = []
    for g in ("gate1", "gate2", "gate3"):
        reasons += cert.get(g, {}).get("reason_codes", [])
    return {"decision": f"REJECTED: {', '.join(reasons) or 'no reason codes'}"}


def router(state: AgentState) -> str:
    """Conditional edge — approval routes to execute, else to rejected."""
    return "execute" if state["certificate"].get("approves") else "rejected"


# ── Graph wiring ──────────────────────────────────────────────────

def build_graph():
    g = StateGraph(AgentState)
    g.add_node("intent",   intent_node)
    g.add_node("propose",  propose_node)
    g.add_node("verify",   verify_node)
    g.add_node("execute",  execute_node)
    g.add_node("rejected", rejected_node)

    g.set_entry_point("intent")
    g.add_edge("intent",  "propose")
    g.add_edge("propose", "verify")
    g.add_conditional_edges("verify", router,
                            {"execute": "execute", "rejected": "rejected"})
    g.add_edge("execute",  END)
    g.add_edge("rejected", END)
    return g.compile()


def main() -> None:
    graph = build_graph()
    for intent in [
        "Funding is strongly positive, go long.",
        "Funding is strongly negative, go short.",
        "Funding is positive but I want to go short anyway.",   # Gate 1 will reject
    ]:
        result = graph.invoke({"intent": intent})
        print(f"intent:    {intent}")
        print(f"proposal:  {result['proposal']}")
        print(f"decision:  {result['decision']}\n")


if __name__ == "__main__":
    main()
