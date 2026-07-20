"""DataLab-backed Markdown OCR adapter for scanned documents."""
from __future__ import annotations

import math
import time
from collections.abc import Callable
from typing import Any

from app.core.config import Settings, settings
from app.domain.schemas import Block, BlockType, PageParseResult
from app.engines.base import EngineParseResult, ParseEngine


class DataLabFastEngine(ParseEngine):
    """Convert a scanned document through DataLab and expose the local parse contract."""

    name = "datalab"

    def __init__(
        self,
        app_settings: Settings = settings,
        *,
        client_factory: Callable[[str], Any] | None = None,
    ) -> None:
        self.settings = app_settings
        self._client_factory = client_factory or self._default_client_factory

    @staticmethod
    def _default_client_factory(api_key: str) -> Any:
        from datalab_sdk import DatalabClient  # type: ignore

        return DatalabClient(api_key=api_key)

    def parse(self, input_path: str, lang_hint: str = "auto") -> EngineParseResult:
        del lang_hint
        if not self.settings.datalab_api_key:
            raise RuntimeError("DataLab OCR requires DATALAB_API_KEY")

        try:
            from datalab_sdk.models import ConvertOptions  # type: ignore

            started = time.perf_counter()
            client = self._client_factory(self.settings.datalab_api_key)
            timeout = max(1.0, self.settings.fast_ocr_datalab_timeout_seconds)
            result = client.convert(
                file_path=input_path,
                options=ConvertOptions(
                    mode=self.settings.fast_ocr_datalab_mode,
                    output_format="markdown",
                    paginate=True,
                ),
                max_polls=max(1, math.ceil(timeout)),
                poll_interval=1,
            )
            duration = time.perf_counter() - started
        except Exception as exc:
            raise RuntimeError(f"DataLab OCR request failed: {exc}") from exc

        if not getattr(result, "success", False) or getattr(result, "status", "") != "complete":
            error = getattr(result, "error", None) or f"status={getattr(result, 'status', 'unknown')}"
            raise RuntimeError(f"DataLab OCR did not complete: {error}")

        markdown = (getattr(result, "markdown", None) or "").strip()
        if not markdown:
            raise RuntimeError("DataLab OCR returned no usable Markdown")

        page_count = self._page_count(result, markdown)
        metadata = {
            "runtime": getattr(result, "runtime", None),
            "cost_breakdown": getattr(result, "cost_breakdown", None),
            "page_count": page_count,
            "mode": self.settings.fast_ocr_datalab_mode,
            "duration": duration,
        }
        return EngineParseResult(
            engine_name=self.name,
            pages=self._build_pages(markdown, page_count),
            markdown=markdown,
            raw={"datalab": metadata},
        )

    @staticmethod
    def _page_count(result: Any, markdown: str) -> int:
        value = getattr(result, "page_count", None)
        if isinstance(value, int) and value > 0:
            return value
        return max(1, markdown.count("\n---\n") + 1)

    @classmethod
    def _build_pages(cls, markdown: str, page_count: int) -> list[PageParseResult]:
        block = Block(
            block_id="datalab_markdown",
            type=BlockType.text,
            content=markdown,
            confidence=0.0,
            page_index=0,
            source_engine=cls.name,
        )
        return [
            PageParseResult(
                page_index=index,
                blocks=[block] if index == 0 else [],
                reading_order=[block.block_id] if index == 0 else [],
                source_engine=cls.name,
            )
            for index in range(page_count)
        ]
