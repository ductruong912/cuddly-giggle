from __future__ import annotations

from typing import Any

from app.services.engines.paddle_base import PaddlePipelineEngine


class PaddleOCRVLEngine(PaddlePipelineEngine):
    name = "paddleocr_vl"
    cli_subcommand = "doc_parser"

    def _load_pipeline_cls(self) -> type:
        from paddleocr import PaddleOCRVL  # type: ignore

        return PaddleOCRVL

    def _extra_kwargs(self) -> dict[str, Any]:
        if self.settings.paddleocr_vl_pipeline_version:
            return {"pipeline_version": self.settings.paddleocr_vl_pipeline_version}
        return {}

    def _extra_cli_args(self) -> list[str]:
        if self.settings.paddleocr_vl_pipeline_version:
            return ["--pipeline_version", self.settings.paddleocr_vl_pipeline_version]
        return []

    def _unavailable_message(self, py_error: str, cli_error: str) -> str:
        return (
            "PaddleOCR-VL is unavailable. Install paddleocr[doc-parser] and paddlepaddle-gpu, "
            "or ensure `paddleocr` CLI exists in PATH. "
            f"pipeline_version={self.settings.paddleocr_vl_pipeline_version or 'default'}; "
            f"python_api_error={py_error or 'n/a'}; cli_error={cli_error or 'n/a'}"
        )

    def warmup(self, pipeline_cls: type | None = None) -> None:
        if pipeline_cls is None:
            pipeline_cls = self._load_pipeline_cls()
        kwargs = self._build_kwargs(pipeline_cls, "auto")
        self._get_or_create_pipeline(pipeline_cls, kwargs)
