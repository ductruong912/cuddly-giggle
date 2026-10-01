"""Build the live extraction source, including the GPU runtime it depends on.

Kept apart from ``sources`` so a replay run never imports the API stack or the
OCR engines it would otherwise pull in transitively.
"""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import logging

from api.dependencies import (
    get_llm_extractor,
    get_orchestrator,
    warmup_primary_engine,
)
from config.config import settings
from eval.sources import LiveExtractionSource
from services.local_ocr_selector import has_usable_gpu
from services.vl_runtime import build_vl_runtime_manager


logger = logging.getLogger(__name__)

LOCAL_ROUTE = "local"


@contextmanager
def live_extraction_source(route: str) -> Iterator[LiveExtractionSource]:
    """Yield a live source for one route, owning the VL runtime for the run.

    The API starts llama.cpp inside its lifespan. A CLI run has no lifespan, so
    it starts and stops the same runtime here rather than requiring the server
    to be running alongside it.

    Args:
        route: ``local`` for the on-box OCR pipeline.

    Raises:
        ValueError: the route is not one this harness knows how to build.
    """
    if route != LOCAL_ROUTE:
        raise ValueError(f"unknown route {route!r}; expected {LOCAL_ROUTE}")

    runtime_manager = None
    if has_usable_gpu() and settings.paddleocr_vl_use_gguf:
        logger.info("starting the local VL runtime for the evaluation run")
        runtime_manager = build_vl_runtime_manager(warmup=warmup_primary_engine)
        runtime_manager.ensure_ready()

    try:
        parser = get_orchestrator()
        yield LiveExtractionSource(
            parser, get_llm_extractor(), route_label=route, app_settings=settings
        )
    finally:
        if runtime_manager is not None:
            runtime_manager.shutdown()
