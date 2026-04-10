from __future__ import annotations

from fastapi import APIRouter, HTTPException

from python.api.theorem_registry import THEOREMS

router = APIRouter()


@router.get("/verify/{theorem_name}")
async def verify_theorem(theorem_name: str) -> dict:
    entry = THEOREMS.get(theorem_name)
    if entry is None:
        raise HTTPException(status_code=404, detail={"error": "not_found", "message": f"Theorem '{theorem_name}' not found"})
    return {"theorem": theorem_name, **entry}
