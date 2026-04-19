"""
This file demonstrates how an external agent framework integrates
with Veritas. Veritas itself does not depend on this code.

Pattern: LLM proposes → Veritas verifies → caller decides.

An Anthropic model is given a natural-language market description and
a single `propose_trade` tool. It returns a structured TradeProposal
via tool-use. The proposal is POSTed to Veritas's /verify/proposal
endpoint; Veritas runs it through Gate 1 (signal consistency), Gate 2
(constraints), and Gate 3 (portfolio) and returns a Certificate. The
caller (this script) prints the verdicts and stops there. A real
caller would execute the `final_notional_usd` on its venue when
`approves=true`, and surface reason codes when `approves=false`.

Prerequisites:
    pip install -r examples/external_integration/requirements-examples.txt
    export ANTHROPIC_API_KEY=sk-...
    python -m python.api.run        # starts Veritas on http://localhost:8000

Run:
    python examples/external_integration/anthropic_sdk_loop.py
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

import anthropic

VERITAS_URL = os.environ.get("VERITAS_URL", "http://localhost:8000")
MODEL = os.environ.get("VERITAS_EXAMPLE_MODEL", "claude-sonnet-4-6")

PROPOSE_TRADE_TOOL = {
    "name": "propose_trade",
    "description": (
        "Propose a single perp trade for Veritas to verify. Fields must "
        "match Veritas's TradeProposal schema exactly."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "direction":    {"type": "string", "enum": ["LONG", "SHORT"]},
            "notional_usd": {"type": "number", "description": "Notional in USD."},
            "funding_rate": {"type": "number", "description": "Current perp funding rate (decimal/hour)."},
            "price":        {"type": "number", "description": "Current asset price in USD."},
        },
        "required": ["direction", "notional_usd", "funding_rate", "price"],
    },
}


def generate_proposal(market_description: str) -> dict:
    """Ask Claude for a structured trade proposal via tool-use."""
    client = anthropic.Anthropic()
    resp = client.messages.create(
        model=MODEL,
        max_tokens=512,
        tools=[PROPOSE_TRADE_TOOL],
        tool_choice={"type": "tool", "name": "propose_trade"},
        messages=[{"role": "user", "content": market_description}],
    )
    for block in resp.content:
        if block.type == "tool_use" and block.name == "propose_trade":
            return dict(block.input)
    raise RuntimeError("Model did not produce a propose_trade tool call")


def verify(proposal: dict, equity: float = 10_000.0) -> dict:
    """POST the proposal to Veritas and return the certificate JSON."""
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
        return {"error": str(e), "approves": False}


def render(proposal: dict, cert: dict) -> None:
    print(f"proposal: {json.dumps(proposal)}")
    if "error" in cert:
        print(f"  veritas error: {cert['error']}"); return
    for gate in ("gate1", "gate2", "gate3"):
        g = cert.get(gate, {})
        codes = g.get("reason_codes", [])
        extra = f" → ${g['new_notional_usd']:,.0f}" if g.get("verdict") == "resize" else ""
        tail = f" [{', '.join(codes)}]" if codes else ""
        print(f"  {gate}: {g.get('verdict')}{extra}{tail}")
    print(f"  approves: {cert.get('approves')}  final_notional: ${cert.get('final_notional_usd', 0):,.0f}")


def main() -> None:
    prompt = (
        "Hyperliquid BTC perp, current price ~$68,000, funding rate is running "
        "+0.12%/hr. Equity $10,000. Propose a trade sized around $1,500 notional."
    )
    proposal = generate_proposal(prompt)
    cert = verify(proposal)
    render(proposal, cert)


if __name__ == "__main__":
    main()
