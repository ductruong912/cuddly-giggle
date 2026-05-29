from __future__ import annotations

import inspect
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
from typing import Any

from app.core.config import Settings, settings
from app.services.engines.base import EngineParseResult, ParseEngine
from app.services.engines.normalizer import normalize_engine_output


class PaddlePipelineEngine(ParseEngine):
    """Shared "Python API first, CLI fallback" flow for PaddleOCR pipelines.

    Subclasses declare ``name`` and ``cli_subcommand`` and override the small
    hooks below; the recognition flow, pipeline caching and CLI handling are
    shared so the two adapters do not duplicate them.
    """

    cli_subcommand: str

    def __init__(self, app_settings: Settings = settings) -> None:
        self.settings = app_settings
        self._pipeline = None
        self._pipeline_key: tuple[tuple[str, str], ...] | None = None
        self._pipeline_lock = threading.Lock()

    # --- hooks subclasses override -------------------------------------------------
    def _load_pipeline_cls(self) -> type:
        """Import and return the PaddleOCR pipeline class. May raise on failure."""
        raise NotImplementedError

    def _extra_kwargs(self) -> dict[str, Any]:
        """Engine-specific constructor kwargs (e.g. pipeline_version)."""
        return {}

    def _extra_cli_args(self) -> list[str]:
        """Engine-specific CLI args (e.g. --pipeline_version)."""
        return []

    def _unavailable_message(self, py_error: str, cli_error: str) -> str:
        """Error raised when neither the Python API nor the CLI is usable."""
        raise NotImplementedError

    # --- shared flow ---------------------------------------------------------------
    def parse(self, input_path: str, lang_hint: str = "auto") -> EngineParseResult:
        # 1) Prefer official Python API when available.
        raw, py_error = self._try_python_api(input_path, lang_hint)
        cli_error = ""
        if raw is None:
            # 2) Fallback to CLI wrapper.
            raw, cli_error = self._try_cli(input_path, lang_hint)
        if raw is None:
            raise RuntimeError(self._unavailable_message(py_error, cli_error))

        pages, markdown, normalized_raw = normalize_engine_output(raw, self.name)
        return EngineParseResult(engine_name=self.name, pages=pages, markdown=markdown, raw=normalized_raw)

    def _try_python_api(self, input_path: str, lang_hint: str) -> tuple[dict[str, Any] | None, str]:
        try:
            pipeline_cls = self._load_pipeline_cls()
        except Exception as exc:
            return None, f"import_error: {exc}"

        kwargs = self._build_kwargs(pipeline_cls, lang_hint)
        try:
            pipeline = self._get_or_create_pipeline(pipeline_cls, kwargs)
            return pipeline.predict(input_path), ""
        except Exception as exc:
            return None, f"predict_error: {exc}"

    def _try_cli(self, input_path: str, lang_hint: str) -> tuple[dict[str, Any] | None, str]:
        cli_bin = shutil.which("paddleocr")
        if cli_bin is None:
            return None, "paddleocr_cli_not_found"

        with tempfile.TemporaryDirectory(prefix=f"{self.name}_") as tmp_dir:
            cmd = [cli_bin, self.cli_subcommand, "-i", input_path, "--save_path", tmp_dir]
            cmd.extend(self._extra_cli_args())
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

            return self._collect_cli_output(Path(tmp_dir))

    @staticmethod
    def _collect_cli_output(root: Path) -> tuple[dict[str, Any] | None, str]:
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
        kwargs.update(self._extra_kwargs())
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
