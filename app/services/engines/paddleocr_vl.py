from __future__ import annotations

import inspect
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
from typing import Any

from app.core.config import settings
from app.services.engines.base import EngineParseResult, ParseEngine
from app.services.engines.normalizer import normalize_engine_output


class PaddleOCRVLEngine(ParseEngine):
    name = "paddleocr_vl"

    def __init__(self, app_settings=settings) -> None:  # type: ignore[no-untyped-def]
        self.settings = app_settings
        self._pipeline = None
        self._pipeline_key: tuple[tuple[str, str], ...] | None = None
        self._pipeline_lock = threading.Lock()

    def parse(self, input_path: str, lang_hint: str = "auto") -> EngineParseResult:
        py_error = ""
        cli_error = ""
        # 1) Prefer official Python API when available.
        raw, py_error = self._try_python_api(input_path, lang_hint)
        if raw is None:
            # 2) Fallback to CLI wrapper.
            raw, cli_error = self._try_cli(input_path, lang_hint)
        if raw is None:
            raise RuntimeError(
                "PaddleOCR-VL is unavailable. Install paddleocr[doc-parser] and paddlepaddle-gpu, "
                "or ensure `paddleocr` CLI exists in PATH. "
                f"pipeline_version={self.settings.paddleocr_vl_pipeline_version or 'default'}; "
                f"python_api_error={py_error or 'n/a'}; cli_error={cli_error or 'n/a'}"
            )

        pages, markdown, normalized_raw = normalize_engine_output(raw, self.name)
        return EngineParseResult(engine_name=self.name, pages=pages, markdown=markdown, raw=normalized_raw)

    def warmup(self, pipeline_cls: type | None = None) -> None:
        if pipeline_cls is None:
            from paddleocr import PaddleOCRVL  # type: ignore

            pipeline_cls = PaddleOCRVL
        kwargs = self._build_kwargs(pipeline_cls, "auto")
        self._get_or_create_pipeline(pipeline_cls, kwargs)

    def _try_python_api(self, input_path: str, lang_hint: str) -> tuple[dict[str, Any] | None, str]:
        try:
            from paddleocr import PaddleOCRVL  # type: ignore
        except Exception as exc:
            return None, f"import_error: {exc}"

        kwargs: dict[str, Any] = self._build_kwargs(PaddleOCRVL, lang_hint)

        try:
            pipeline = self._get_or_create_pipeline(PaddleOCRVL, kwargs)
            output = pipeline.predict(input_path)
            return output, ""
        except Exception as exc:
            return None, f"predict_error: {exc}"

    def _try_cli(self, input_path: str, lang_hint: str) -> tuple[dict[str, Any] | None, str]:
        cli_bin = shutil.which("paddleocr")
        if cli_bin is None:
            return None, "paddleocr_cli_not_found"

        with tempfile.TemporaryDirectory(prefix="paddleocr_vl_") as tmp_dir:
            cmd = [cli_bin, "doc_parser", "-i", input_path, "--save_path", tmp_dir]
            if self.settings.paddleocr_vl_pipeline_version:
                cmd.extend(["--pipeline_version", self.settings.paddleocr_vl_pipeline_version])
            if lang_hint != "auto":
                cmd.extend(["--lang", lang_hint])
            if self.settings.ocr_device:
                cmd.extend(["--device", self.settings.ocr_device])
            if self.settings.ocr_inference_engine:
                cmd.extend(["--engine", self.settings.ocr_inference_engine])
            completed = subprocess.run(cmd, capture_output=True, text=True, check=False)
            if completed.returncode != 0:
                stderr = (completed.stderr or "").strip()
                stdout = (completed.stdout or "").strip()
                return None, f"cli_returncode={completed.returncode}, stderr={stderr or stdout}"

            root = Path(tmp_dir)
            json_files = sorted(root.rglob("*.json"))
            md_files = sorted(root.rglob("*.md"))
            if not json_files and not md_files:
                return None, "cli_no_output_files"

            payload: dict[str, Any] = {}
            pages: list[dict[str, Any]] = []
            for file_path in json_files:
                try:
                    data = json.loads(file_path.read_text(encoding="utf-8"))
                except Exception:
                    continue
                if isinstance(data, dict) and "pages" in data:
                    pages.extend(data["pages"] if isinstance(data["pages"], list) else [])
                elif isinstance(data, dict):
                    pages.append(data)

            payload["pages"] = pages
            if md_files:
                payload["markdown"] = md_files[0].read_text(encoding="utf-8", errors="ignore")
            return payload, ""

    def _build_kwargs(self, engine_cls: type, lang_hint: str) -> dict[str, Any]:
        kwargs: dict[str, Any] = {}

        try:
            signature = inspect.signature(engine_cls.__init__)
        except Exception:
            signature = None

        if signature is not None and "lang" in signature.parameters and lang_hint != "auto":
            kwargs["lang"] = lang_hint

        # Common args accepted by PaddleOCR parser via **kwargs.
        if self.settings.paddleocr_vl_pipeline_version:
            kwargs["pipeline_version"] = self.settings.paddleocr_vl_pipeline_version
        if self.settings.ocr_device:
            kwargs["device"] = self.settings.ocr_device
        if self.settings.ocr_inference_engine:
            kwargs["engine"] = self.settings.ocr_inference_engine
        return kwargs

    def _get_or_create_pipeline(self, pipeline_cls: type, kwargs: dict[str, Any]):  # type: ignore[no-untyped-def]
        key = tuple(sorted((str(k), str(v)) for k, v in kwargs.items()))
        with self._pipeline_lock:
            if self._pipeline is None or self._pipeline_key != key:
                self._pipeline = pipeline_cls(**kwargs)
                self._pipeline_key = key
        return self._pipeline
