from __future__ import annotations

import inspect
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
from typing import Any, Callable

from app.core.config import Settings, settings
from app.domain.schemas import PageParseResult
from app.engines.base import EngineParseResult, ParseEngine
from app.engines.normalizer import normalize_engine_output


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
        self._inference_lock = threading.Lock()

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
        # Dense PDFs (e.g. vector CAD title blocks) read far more reliably when each
        # page is rasterized to a standalone image and OCR'd alone, instead of letting
        # PaddleOCR render+batch the whole PDF. Fall back to the original flow if
        # rasterization is disabled, the input is not a PDF, or rendering fails.
        page_images, cleanup = self._rasterize_pdf_pages(input_path)
        try:
            if page_images is None:
                return self._parse_single(input_path, lang_hint)
            return self._merge_page_results(
                [self._parse_single(image_path, lang_hint) for image_path in page_images]
            )
        finally:
            cleanup()

    def _parse_single(self, input_path: str, lang_hint: str) -> EngineParseResult:
        # 1) Prefer official Python API when available.
        raw, py_error = self._try_python_api(input_path, lang_hint)
        cli_error = ""
        if raw is None:
            # 2) Fallback to CLI wrapper.
            raw, cli_error = self._try_cli(input_path, lang_hint)
        if raw is None:
            raise RuntimeError(self._unavailable_message(py_error, cli_error))

        pages, markdown, normalized_raw = normalize_engine_output(raw, self.name, self.settings)
        return EngineParseResult(engine_name=self.name, pages=pages, markdown=markdown, raw=normalized_raw)

    def _rasterize_pdf_pages(self, input_path: str) -> tuple[list[str] | None, Callable[[], None]]:
        noop: Callable[[], None] = lambda: None
        if not self.settings.pdf_rasterize_enabled or Path(input_path).suffix.lower() != ".pdf":
            return None, noop
        try:
            # pyrefly: ignore [missing-import]
            import fitz  # PyMuPDF
        except Exception:
            return None, noop  # PyMuPDF missing: keep the original whole-PDF flow.

        tmp_dir = Path(tempfile.mkdtemp(prefix=f"{self.name}_pages_"))
        try:
            zoom = max(self.settings.pdf_rasterize_dpi, 72) / 72.0
            matrix = fitz.Matrix(zoom, zoom)
            image_paths: list[str] = []
            doc = fitz.open(input_path)
            try:
                for page_index, page in enumerate(doc):
                    pixmap = page.get_pixmap(matrix=matrix, alpha=False)
                    image_path = tmp_dir / f"page_{page_index:04d}.png"
                    pixmap.save(str(image_path))
                    image_paths.append(str(image_path))
            finally:
                doc.close()
        except Exception:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            return None, noop

        if not image_paths:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            return None, noop

        return image_paths, lambda: shutil.rmtree(tmp_dir, ignore_errors=True)

    def _merge_page_results(self, results: list[EngineParseResult]) -> EngineParseResult:
        merged_pages: list[PageParseResult] = []
        markdown_parts: list[str] = []
        page_no = 0
        for result in results:
            for page in result.pages:
                blocks = [block.model_copy(update={"page_index": page_no}) for block in page.blocks]
                tables = [table.model_copy(update={"page_index": page_no}) for table in page.tables]
                merged_pages.append(page.model_copy(update={"page_index": page_no, "blocks": blocks, "tables": tables}))
                page_no += 1
            if result.markdown and result.markdown.strip():
                markdown_parts.append(result.markdown)
        markdown = "\n\n".join(markdown_parts) or None
        return EngineParseResult(engine_name=self.name, pages=merged_pages, markdown=markdown, raw={})

    def _try_python_api(self, input_path: str, lang_hint: str) -> tuple[dict[str, Any] | None, str]:
        try:
            pipeline_cls = self._load_pipeline_cls()
        except Exception as exc:
            return None, f"import_error: {exc}"

        kwargs = self._build_kwargs(pipeline_cls, lang_hint)
        try:
            pipeline = self._get_or_create_pipeline(pipeline_cls, kwargs)
            
            predict_kwargs: dict[str, Any] = {}
            if self.name == "paddleocr_vl":
                predict_kwargs["max_pixels"] = self.settings.paddleocr_vl_max_pixels

            if self.settings.paddleocr_vl_use_gguf:
                # GGUF backend is remote, so calling predict is thread-safe and doesn't require the GPU process-level lock.
                output = pipeline.predict(input_path, **predict_kwargs)
            else:
                with self._inference_lock:
                    output = pipeline.predict(input_path, **predict_kwargs)
            return output, ""
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


class PaddleOCRVLEngine(PaddlePipelineEngine):
    name = "paddleocr_vl"
    cli_subcommand = "doc_parser"

    def _load_pipeline_cls(self) -> type:
        from paddleocr import PaddleOCRVL  # type: ignore

        return PaddleOCRVL

    def _extra_kwargs(self) -> dict[str, Any]:
        kwargs: dict[str, Any] = {}
        if self.settings.paddleocr_vl_pipeline_version:
            kwargs["pipeline_version"] = self.settings.paddleocr_vl_pipeline_version
        if self.settings.paddleocr_vl_use_gguf:
            kwargs.update(self._remote_vl_kwargs())
        
        # Override ignore labels (e.g. empty list to keep headers and footers)
        kwargs["markdown_ignore_labels"] = list(self.settings.paddleocr_vl_markdown_ignore_labels)
        return kwargs

    def _extra_cli_args(self) -> list[str]:
        args: list[str] = []
        if self.settings.paddleocr_vl_pipeline_version:
            args.extend(["--pipeline_version", self.settings.paddleocr_vl_pipeline_version])
        if self.settings.paddleocr_vl_use_gguf:
            for key, value in self._remote_vl_kwargs().items():
                args.extend([f"--{key}", str(value)])
        return args

    def _remote_vl_kwargs(self) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "vl_rec_backend": self.settings.paddleocr_vl_rec_backend or "llama-cpp-server",
            "vl_rec_server_url": self.settings.paddleocr_vl_rec_server_url
            or f"http://{self.settings.llama_server_host}:{self.settings.llama_server_port}/v1",
            "vl_rec_max_concurrency": self.settings.paddleocr_vl_rec_max_concurrency or 1,
            "vl_rec_api_model_name": self.settings.paddleocr_vl_rec_api_model_name or "paddleocr-vl",
        }
        if self.settings.paddleocr_vl_rec_api_key:
            kwargs["vl_rec_api_key"] = self.settings.paddleocr_vl_rec_api_key
        return kwargs

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


class PPStructureV3Engine(PaddlePipelineEngine):
    name = "pp_structure_v3"
    cli_subcommand = "pp_structurev3"

    def _load_pipeline_cls(self) -> type:
        from paddleocr import PPStructureV3  # type: ignore

        return PPStructureV3

    def _unavailable_message(self, py_error: str, cli_error: str) -> str:
        return (
            "PP-StructureV3 is unavailable. Install paddleocr and paddlepaddle-gpu, "
            "or ensure `paddleocr` CLI exists in PATH. "
            f"python_api_error={py_error or 'n/a'}; cli_error={cli_error or 'n/a'}"
        )
