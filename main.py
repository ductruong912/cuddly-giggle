"""Entrypoint: start the ASGI server. All wiring happens in the app lifespan."""
from __future__ import annotations

import os
import warnings

warnings.filterwarnings("ignore", message="No ccache found")

# pyrefly: ignore [missing-import]
import uvicorn

from api.application import app


def silence_known_warnings() -> None:
    """Suppress third-party warnings that are expected in the supported setups."""
    warnings.filterwarnings("ignore", message=r"'llama-cpp-server' does not support")


def main() -> None:
    """Run the API with a single worker process; concurrency is bounded in-process."""
    silence_known_warnings()
    uvicorn.run(
        app,
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "8000")),
        reload=False,
        timeout_keep_alive=int(os.getenv("KEEP_ALIVE_SECONDS", "30")),
    )


if __name__ == "__main__":
    main()
