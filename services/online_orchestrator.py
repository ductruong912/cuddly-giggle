"""Dedicated DataLab/SuryaOCR parse service."""
from __future__ import annotations

import itertools
import uuid

from config.config import Settings, settings
from core.domain.schemas import ParseDecision, ParseResponse
from core.engines.base import ParseEngine
from core.engines.fast_datalab import DataLabFastEngine


class OnlineParseOrchestrator:
    """Run online OCR through DataLab without a local fallback."""

    def __init__(
        self,
        app_settings: Settings = settings,
        *,
        engine: ParseEngine | None = None,
    ) -> None:
        self.engine = engine or DataLabFastEngine(app_settings)

    def parse(self, input_path: str, *, request_id: str | None = None) -> ParseResponse:
        result = self.engine.parse(input_path)
        pages = result.pages
        return ParseResponse(
            request_id=request_id or f"req_{uuid.uuid4().hex[:12]}",
            decision=ParseDecision(reason="Online DataLab SuryaOCR completed."),
            pages=pages,
            blocks=list(itertools.chain.from_iterable(page.blocks for page in pages)),
            tables=list(itertools.chain.from_iterable(page.tables for page in pages)),
            reading_order=list(itertools.chain.from_iterable(page.reading_order for page in pages)),
            markdown=result.markdown,
            engine_name=result.engine_name,
            engine_metadata={"provider": "datalab"},
        )
