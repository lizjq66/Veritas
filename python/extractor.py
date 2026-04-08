from __future__ import annotations

"""LLM client placeholder — v0.1 does not call LLM.

In v0.1, assumption extraction is hardcoded in the Lean core
(Strategy.extractAssumptions). This module exists as a stub for v0.2+
where the LLM will dynamically generate assumption descriptions from
market context.

The LLM is an UNTRUSTED ORACLE — its outputs are always validated by
the Lean core before being acted on. This is the Veritas philosophy:
LLM proposes, Lean disposes.
"""


class LLMExtractor:
    """Stub for v0.2+ dynamic assumption extraction via LLM."""

    def __init__(self, model: str = "claude-sonnet-4-20250514") -> None:
        self.model = model

    def extract_assumptions(self, market_context: dict) -> list[dict]:
        """v0.2: will call LLM to generate assumption descriptions.
        v0.1: unused — Lean core handles extraction."""
        raise NotImplementedError(
            "LLM extraction is a v0.2 feature. "
            "v0.1 uses hardcoded assumptions in Lean core."
        )
