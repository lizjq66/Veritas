"""Read-only enforcement middleware.

Physical enforcement of the trust boundary: the API is observation only.
Veritas's behavior is determined by its Lean core, not by HTTP requests.
"""

from __future__ import annotations

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

_ALLOWED_METHODS = {"GET", "HEAD", "OPTIONS"}

_REJECT_BODY = (
    '{"error": "veritas_api_is_read_only", '
    '"message": "Veritas\'s behavior is determined by its Lean core. '
    'The API is observation only."}'
)


class ReadOnlyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.method not in _ALLOWED_METHODS:
            return Response(
                content=_REJECT_BODY,
                status_code=405,
                media_type="application/json",
            )
        return await call_next(request)
