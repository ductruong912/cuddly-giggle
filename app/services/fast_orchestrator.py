"""Parse-service facade for the lightweight CPU OCR endpoint."""
from __future__ import annotations

import itertools
import logging
import uuid

from app.core.config import Settings, settings
from app.domain.schemas import ParseDecision, ParseResponse
from app.engines.base import ParseEngine
from app.engines.fast_datalab import DataLabFastEngine
from app.engines.fast_paddle import PaddleOCRFastEngine


logger = logging.getLogger(__name__)


class FastParseOrchestrator:
    """Select the configured fast OCR provider and preserve the parse contract."""

    def __init__(
        self,
        engine: ParseEngine | None = None,
        app_settings: Settings = settings,
        *,
        datalab_engine: ParseEngine | None = None,
        local_engine: ParseEngine | None = None,
    ) -> None:
        self.settings = app_settings
        if engine is not None:
            # Compatibility injection used by existing tests and callers.
            self.local_engine = engine
            self.datalab_engine = None
            self.engine = engine
            return

        self.local_engine = local_engine or PaddleOCRFastEngine(app_settings)
        if app_settings.fast_ocr_provider == "datalab":
            self.datalab_engine = datalab_engine or DataLabFastEngine(app_settings)
            self.engine = self.datalab_engine
        else:
            self.datalab_engine = datalab_engine
            self.engine = self.local_engine

    def parse(self, input_path: str, *, request_id: str | None = None) -> ParseResponse:
        provider = "datalab" if self.engine is self.datalab_engine else "local"
        fallback = False
        fallback_from: str | None = None
        try:
            result = self.engine.parse(input_path)
        except Exception as exc:
            if provider != "datalab" or not self.settings.fast_ocr_datalab_fallback:
                raise
            logger.warning("datalab-ocr failed error=%s fallback=local", exc)
            fallback = True
            fallback_from = "datalab"
            result = self.local_engine.parse(input_path)

        engine_metadata = dict(result.raw.get("datalab", {})) if isinstance(result.raw, dict) else {}
        engine_metadata.update(
            {
                "provider": provider if not fallback else "local",
                "fallback": fallback,
            }
        )
        if fallback_from:
            engine_metadata["fallback_from"] = fallback_from
        pages = result.pages
        return ParseResponse(
            request_id=request_id or f"req_{uuid.uuid4().hex[:12]}",
            decision=ParseDecision(
                reason=("Fast DataLab OCR completed." if provider == "datalab" and not fallback else "Fast CPU OCR completed.")
            ),
            pages=pages,
            blocks=list(itertools.chain.from_iterable(page.blocks for page in pages)),
            tables=list(itertools.chain.from_iterable(page.tables for page in pages)),
            reading_order=list(itertools.chain.from_iterable(page.reading_order for page in pages)),
            markdown=result.markdown,
            engine_name=result.engine_name,
            engine_metadata=engine_metadata,
        )

    def warmup(self) -> None:
        """Warm the local engine when it is active or needed as fallback."""
        if self.settings.fast_ocr_provider == "datalab" and not self.settings.fast_ocr_datalab_fallback:
            return
        warmup = getattr(self.local_engine, "warmup", None)
        if not callable(warmup):
            raise RuntimeError(
                f"Fast OCR engine {self.local_engine.__class__.__name__} does not support warmup."
            )
        warmup()
