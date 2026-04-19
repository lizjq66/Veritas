"""Write-boundary middleware.

Veritas's API exposes two kinds of endpoints:

  1. Verification endpoints (``/verify/*``) — POST is allowed because
     each call is a pure function against the Lean kernel. Nothing in
     the journal is mutated; the response is a certificate derived
     from the request and the compiled core.

  2. Observation endpoints (everything else) — read-only. POST, PUT,
     DELETE, PATCH are rejected. Veritas's state evolves only through
     the runner's own journal writes, never through HTTP callers.
"""

from __future__ import annotations

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

_READ_METHODS = {"GET", "HEAD", "OPTIONS"}
_VERIFY_PREFIX = "/verify"

_REJECT_BODY = (
    '{"error": "veritas_api_write_denied", '
    '"message": "This endpoint is observation-only. '
    'Proposal verification is available via POST /verify/proposal, '
    '/verify/signal, /verify/constraints, /verify/portfolio."}'
)


class ReadOnlyMiddleware(BaseHTTPMiddleware):
    """Reject write methods on non-verification endpoints."""

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        method = request.method
        if method in _READ_METHODS:
            return await call_next(request)
        # POSTs are allowed only on the verification surface.
        if method == "POST" and path.startswith(_VERIFY_PREFIX):
            return await call_next(request)
        return Response(
            content=_REJECT_BODY,
            status_code=405,
            media_type="application/json",
        )
