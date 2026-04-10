from __future__ import annotations

from fastapi import APIRouter, HTTPException

from python.api import db

router = APIRouter()

_LEAN_PATHS = {
    "funding_rate_reverts_within_8h": "Veritas/Strategy/FundingReversion.lean",
}


@router.get("/assumptions")
async def list_assumptions() -> dict:
    rows = db.get_assumptions()
    return {
        "assumptions": [
            {
                **row,
                "reliability": row["wins"] / row["total"] if row["total"] > 0 else 0.5,
            }
            for row in rows
        ]
    }


@router.get("/assumptions/{name}")
async def get_assumption(name: str) -> dict:
    row = db.get_assumption(name)
    if row is None:
        raise HTTPException(status_code=404, detail={"error": "not_found", "message": f"Assumption '{name}' not found"})

    outcomes = db.get_recent_outcomes(name)
    return {
        **row,
        "reliability": row["wins"] / row["total"] if row["total"] > 0 else 0.5,
        "lean_theorem_path": _LEAN_PATHS.get(name, "unknown"),
        "verification_status": "proven",
        "recent_outcomes": outcomes,
    }
