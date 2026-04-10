"""Entry point for the Veritas API server.

Usage:
    python -m python.api.run
    python -m python.api.run --port 8080
"""

from __future__ import annotations

import sys

import uvicorn


def main() -> None:
    port = 8000
    if "--port" in sys.argv:
        idx = sys.argv.index("--port")
        port = int(sys.argv[idx + 1])

    uvicorn.run(
        "python.api.server:app",
        host="127.0.0.1",
        port=port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
