from __future__ import annotations

import inspect
import json
import logging
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import time
from typing import Any, Callable

from config.config import Settings, settings
from config.pipeline_logging import current_source_document, pipeline_message
from core.domain.schemas import PageParseResult
from core.engines.base import EngineParseResult, ParseEngine
from core.engines.normalizer import normalize_engine_output
from core.preprocess import preprocess_file
from services.model_assets import require_model_profile


logger = logging.getLogger(__name__)


class PaddlePipelineEngine(ParseEngine):
    """Shared "Python API first, CLI fallback" flow for PaddleOCR pipelines.

    Subclasses declare ``name`` and ``cli_subcommand`` and override the small
    hooks below; the recognition flow, pipeline caching and CLI handling are
    shared so the two adapters do not duplicate them.
    """

    model_profile: str
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
        page_images, cleanup = self._prepare_page_images(input_path)
        try:
            if page_images is None:
                return self._parse_with_progress(input_path, lang_hint, page_number=1, page_count=1)

            logger.info(
                pipeline_message("PHASE 2", "ocr started engine=%s pages=%s"),
                self.name,
                len(page_images),
            )
            results = [
                self._parse_with_progress(
                    image_path,
                    lang_hint,
                    page_number=page_number,
                    page_count=len(page_images),
                )
                for page_number, image_path in enumerate(page_images, start=1)
            ]
            return self._merge_page_results(results)
        finally:
            cleanup()

    def _parse_with_progress(
        self,
        input_path: str,
        lang_hint: str,
        *,
        page_number: int,
        page_count: int,
    ) -> EngineParseResult:
        logger.info(
            pipeline_message("PHASE 2", "ocr page=%s/%s started"),
            page_number,
            page_count,
        )
        started = time.perf_counter()
        result = self._parse_single(input_path, lang_hint)
        logger.info(
            pipeline_message("PHASE 2", "ocr page=%s/%s completed duration=%.3fs"),
            page_number,
            page_count,
            time.perf_counter() - started,
        )
        return result

    def _parse_single(self, input_path: str, lang_hint: str) -> EngineParseResult:
        # Enforce setup for both adapters before importing models or invoking CLI.
        if os.getenv("CUDDLY_GIGGLE_MODEL_SETUP") != "1":
            require_model_profile(self.settings, self.model_profile)
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

    def _prepare_page_images(self, input_path: str) -> tuple[list[str] | None, Callable[[], None]]:
        """Produce the page images OCR should read, cleaned up if preprocessing is on.

        Returns ``(None, noop)`` to mean "hand the original path straight to the
        pipeline", which is the flow for a PDF when rasterization is off or has
        failed, and for any input the preprocessing chain declined to touch.
        """
        page_images, cleanup = self._rasterize_pdf_pages(input_path)
        if not self.settings.preprocess_enabled:
            return page_images, cleanup

        document_stem = self._document_stem(input_path)
        try:
            if page_images is not None:
                # Rasterized pages are throwaway temp files, so they are rewritten
                # in place and removed by the existing cleanup.
                for page_number, image_path in enumerate(page_images, start=1):
                    self._preprocess_page(
                        image_path, image_path, document_stem, page_number, allow_exif=False
                    )
                return page_images, cleanup
            return self._preprocess_standalone_input(input_path, document_stem)
        except Exception:
            # Never let cleanup leak because preprocessing raised.
            logger.warning("page preprocessing failed for %s; using the raw pages", input_path, exc_info=True)
            return page_images, cleanup

    @staticmethod
    def _document_stem(input_path: str) -> str:
        """Name saved diagnostics after the uploaded document, not its staged UUID."""
        source = current_source_document()
        stem = Path(source).stem if source else Path(input_path).stem
        # The stem becomes a directory name, and an upload can be called anything.
        safe = "".join(ch for ch in stem if ch.isalnum() or ch in "-_. ").strip(" .")
        return safe or "document"

    def _preprocess_standalone_input(
        self, input_path: str, document_stem: str
    ) -> tuple[list[str] | None, Callable[[], None]]:
        """Clean a single image input into a temp copy, never over the source file."""
        noop: Callable[[], None] = lambda: None
        if Path(input_path).suffix.lower() == ".pdf":
            # Rasterization is off or failed, so there is no page image to clean;
            # PaddleOCR renders the PDF itself.
            return None, noop

        tmp_dir = Path(tempfile.mkdtemp(prefix=f"{self.name}_pre_"))
        destination = tmp_dir / f"page_0000{Path(input_path).suffix or '.png'}"
        result = self._preprocess_page(input_path, str(destination), document_stem, 1)
        if not result.changed:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            return None, noop
        return [result.path], lambda: shutil.rmtree(tmp_dir, ignore_errors=True)

    def _preprocess_page(
        self,
        source_path: str,
        destination_path: str,
        document_stem: str,
        page_number: int,
        *,
        allow_exif: bool = True,
    ):  # type: ignore[no-untyped-def]
        result = preprocess_file(
            source_path,
            output_path=destination_path,
            app_settings=self.settings,
            debug_name=f"{document_stem}/page_{page_number:04d}",
            allow_exif=allow_exif,
        )
        if result.changed:
            logger.info(
                pipeline_message("PHASE 2", "preprocess page=%s duration=%.3fs steps=%s"),
                page_number,
                result.total_seconds,
                result.summary(),
            )
        return result

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
        if os.getenv("CUDDLY_GIGGLE_MODEL_SETUP") != "1":
            require_model_profile(self.settings, self.model_profile)
        key = tuple(sorted((str(k), str(v)) for k, v in kwargs.items()))
        with self._pipeline_lock:
            if self._pipeline is None or self._pipeline_key != key:
                self._pipeline = pipeline_cls(**kwargs)
                self._pipeline_key = key
        return self._pipeline

    def warmup(self, pipeline_cls: type | None = None) -> None:
        """Create and cache the configured pipeline without parsing a document."""
        if pipeline_cls is None:
            pipeline_cls = self._load_pipeline_cls()
        kwargs = self._build_kwargs(pipeline_cls, "auto")
        self._get_or_create_pipeline(pipeline_cls, kwargs)


class PaddleOCRVLEngine(PaddlePipelineEngine):
    name = "paddleocr_vl"
    model_profile = "gpu"
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
        if self.settings.paddleocr_vl_auto_rotate:
            kwargs["use_doc_orientation_classify"] = True
            kwargs["use_doc_unwarping"] = True

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
        if self.settings.paddleocr_vl_auto_rotate:
            args.extend(["--use_doc_orientation_classify", "True"])
            args.extend(["--use_doc_unwarping", "True"])
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
