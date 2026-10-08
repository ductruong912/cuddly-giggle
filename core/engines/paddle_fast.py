"""Lightweight CPU PaddleOCR adapter for scanned images and PDFs."""
from __future__ import annotations

from collections.abc import Iterable
import json
import logging
import os
from pathlib import Path
import shutil
import threading
import time
from typing import Any

from config.config import Settings, settings
from core.domain.schemas import PageGeometry
from core.engines.base import EngineParseResult, image_page_geometry
from core.engines.normalizer import normalize_engine_output
from core.engines.preview import attach_page_previews, preview_capture_enabled
from core.engines.paddle import PaddlePipelineEngine
from services.model_assets import require_model_profile


logger = logging.getLogger(__name__)


class PaddleOCRFastEngine(PaddlePipelineEngine):
    """Run the general PaddleOCR pipeline with the CPU-oriented v6 profile."""

    name = "paddleocr_fast"
    model_profile = "cpu"

    def __init__(self, app_settings: Settings = settings) -> None:
        self.settings = app_settings
        self._pipeline: Any | None = None
        self._pipeline_lock = threading.Lock()

    def _build_pipeline_kwargs(self) -> dict[str, object]:
        kwargs: dict[str, object] = {
            "device": self.settings.fast_ocr_device,
            "engine": self.settings.fast_ocr_inference_engine,
            "text_detection_model_name": self.settings.fast_ocr_detection_model_name,
            "text_recognition_model_name": self.settings.fast_ocr_recognition_model_name,
            "text_recognition_batch_size": self.settings.fast_ocr_recognition_batch_size,
            "use_doc_orientation_classify": (
                self.settings.fast_ocr_auto_rotate and not self.settings.ocr_external_rotation
            ),
            "use_doc_unwarping": False,
            "use_textline_orientation": False,
        }
        if self.settings.fast_ocr_inference_engine in {"paddle", "paddle_static"}:
            kwargs.update(
                enable_mkldnn=self.settings.fast_ocr_enable_mkldnn,
                cpu_threads=self.settings.fast_ocr_cpu_threads,
            )
        return kwargs

    def _external_auto_rotate(self) -> bool:
        return self.settings.ocr_external_rotation and self.settings.fast_ocr_auto_rotate

    def parse(self, input_path: str, lang_hint: str = "auto") -> EngineParseResult:
        if Path(input_path).suffix.lower() != ".pdf":
            return self._parse_single(input_path, lang_hint)
        page_images, cleanup = self._prepare_page_images(input_path)
        try:
            if page_images is None:
                return self._parse_single(input_path, lang_hint)
            results = [self._parse_single(path, lang_hint, prepared=True) for path in page_images]
            merged = self._merge_page_results(results)
            merged.raw["paddleocr"] = [
                page for result in results for page in result.raw.get("paddleocr", [])
            ]
            return merged
        finally:
            cleanup()

    def _parse_single(
        self, input_path: str, lang_hint: str, *, prepared: bool = False
    ) -> EngineParseResult:
        del lang_hint
        staged_dir: str | None = None
        try:
            if not prepared:
                input_path, staged_dir = self._preprocessed_input(input_path)
            pipeline = self._get_or_create_pipeline()
            page_count = self._get_input_page_count(input_path)
            total_start = time.perf_counter()
            logger.info(
                "fast-ocr started pages=%s device=%s engine=%s threads=%s mkldnn=%s rec_batch=%s",
                page_count,
                self.settings.fast_ocr_device,
                self.settings.fast_ocr_inference_engine,
                self._runtime_threads_label(),
                self._runtime_mkldnn_label(),
                self.settings.fast_ocr_recognition_batch_size,
            )
            output = self._predict_output(pipeline, input_path, page_count)

            normalize_start = time.perf_counter()
            normalized, raw = self._normalize_output(output)
            pages, markdown, normalized_raw = normalize_engine_output(
                normalized,
                source_engine=self.name,
                app_settings=self.settings,
            )
            is_pdf = Path(input_path).suffix.lower() == ".pdf"
            geometry = None
            if not is_pdf and not self.settings.fast_ocr_auto_rotate:
                geometry = image_page_geometry(input_path, matches_original=staged_dir is None and not prepared)
            for page, normalized_page in zip(pages, normalized["pages"]):
                if geometry is not None:
                    page.geometry = geometry
                elif normalized_page.get("image_size"):
                    width, height = normalized_page["image_size"]
                    page.geometry = PageGeometry(
                        width=width,
                        height=height,
                        coordinate_space=(
                            "original" if is_pdf and not self.settings.fast_ocr_auto_rotate
                            else "processed"
                        ),
                    )
            if preview_capture_enabled():
                attach_page_previews(pages, output, input_matches_original=(
                    not prepared and staged_dir is None and (is_pdf or image_page_geometry(input_path, matches_original=True) is not None)
                ))
            logger.info(
                "fast-ocr normalize completed duration=%.3fs",
                time.perf_counter() - normalize_start,
            )
            logger.info(
                "fast-ocr completed pages=%s duration=%.3fs",
                len(output),
                time.perf_counter() - total_start,
            )
            normalized_raw["paddleocr"] = raw
            return EngineParseResult(
                engine_name=self.name,
                pages=pages,
                markdown=markdown,
                raw=normalized_raw,
            )
        except Exception as exc:
            raise RuntimeError(f"Fast PaddleOCR is unavailable: {exc}") from exc
        finally:
            if staged_dir is not None:
                shutil.rmtree(staged_dir, ignore_errors=True)

    def _preprocessed_input(self, input_path: str) -> tuple[str, str | None]:
        """Normalize an image into a temporary copy using the shared page chain."""
        if Path(input_path).suffix.lower() == ".pdf":
            return input_path, None
        if self._external_auto_rotate() and os.getenv("CUDDLY_GIGGLE_MODEL_SETUP") != "1":
            require_model_profile(self.settings, self.model_profile)
        paths, cleanup = self._preprocess_standalone_input(
            input_path, self._document_stem(input_path), auto_rotate=self._external_auto_rotate()
        )
        if paths is None or paths[0] == input_path:
            cleanup()
            return input_path, None
        return paths[0], str(Path(paths[0]).parent)

    def warmup(self) -> None:
        self._get_or_create_pipeline()
        if self._external_auto_rotate():
            from core.preprocess.orientation import warmup_orientation_classifier

            warmup_orientation_classifier()

    def _runtime_threads_label(self) -> object:
        if self.settings.fast_ocr_inference_engine == "onnxruntime":
            return "runtime-default"
        return self.settings.fast_ocr_cpu_threads

    def _runtime_mkldnn_label(self) -> object:
        if self.settings.fast_ocr_inference_engine == "onnxruntime":
            return "n/a"
        return self.settings.fast_ocr_enable_mkldnn

    @staticmethod
    def _predict_output(pipeline: Any, input_path: str, page_count: int) -> list[object]:
        predict_iter = getattr(pipeline, "predict_iter", None)
        if not callable(predict_iter):
            document_start = time.perf_counter()
            output = list(pipeline.predict(input_path))
            logger.info(
                "fast-ocr document completed pages=%s duration=%.3fs",
                len(output),
                time.perf_counter() - document_start,
            )
            return output

        output: list[object] = []
        results = iter(predict_iter(input_path))
        for page_number in range(1, page_count + 1):
            logger.info("fast-ocr page=%s/%s started", page_number, page_count)
            page_start = time.perf_counter()
            try:
                output.append(next(results))
            except StopIteration:
                break
            logger.info(
                "fast-ocr page=%s/%s completed duration=%.3fs",
                page_number,
                page_count,
                time.perf_counter() - page_start,
            )
        return output

    @staticmethod
    def _get_input_page_count(input_path: str) -> int:
        if Path(input_path).suffix.lower() != ".pdf":
            return 1

        import fitz

        with fitz.open(input_path) as document:
            return document.page_count

    def _get_or_create_pipeline(self) -> Any:
        if os.getenv("CUDDLY_GIGGLE_MODEL_SETUP") != "1":
            require_model_profile(self.settings, self.model_profile)
        with self._pipeline_lock:
            if self._pipeline is None:
                initialization_start = time.perf_counter()
                try:
                    from paddleocr import PaddleOCR  # type: ignore
                except Exception as exc:
                    raise RuntimeError(f"Fast PaddleOCR is unavailable: {exc}") from exc
                self._pipeline = PaddleOCR(**self._build_pipeline_kwargs())
                logger.info(
                    "fast-ocr model initialized duration=%.3fs",
                    time.perf_counter() - initialization_start,
                )
            else:
                logger.info("fast-ocr model reused")
        return self._pipeline

    def _normalize_output(self, output: Iterable[object]) -> tuple[dict[str, object], list[dict[str, object]]]:
        pages: list[dict[str, object]] = []
        raw_pages: list[dict[str, object]] = []
        markdown_parts: list[str] = []

        for position, item in enumerate(output):
            result = self._result_to_dict(item)
            raw_pages.append(result)
            payload = result.get("res") if isinstance(result.get("res"), dict) else result
            page_index = self._as_int(payload.get("page_index"), position)
            texts = self._as_list(payload.get("rec_texts"))
            scores = self._as_list(payload.get("rec_scores"))
            boxes = self._as_list(payload.get("rec_boxes"))
            polygons = self._as_list(payload.get("rec_polys"))
            # PaddleX retains the recognition image in the live result but omits
            # it from JSON. Its actual dimensions also cover PDFs rendered internally.
            live = item.get("res", item) if isinstance(item, dict) else {}
            preprocessor = live.get("doc_preprocessor_res", {})
            image = preprocessor.get("output_img") if isinstance(preprocessor, dict) else None
            shape = getattr(image, "shape", ())
            image_size = [int(shape[1]), int(shape[0])] if len(shape) >= 2 else None

            blocks: list[dict[str, object]] = []
            lines: list[str] = []
            numeric_scores: list[float] = []
            for line_index, text_value in enumerate(texts):
                text = str(text_value).strip()
                if not text:
                    continue
                score = self._as_float(scores[line_index] if line_index < len(scores) else None)
                if line_index < len(polygons):
                    box = polygons[line_index]
                else:
                    box = boxes[line_index] if line_index < len(boxes) else []
                blocks.append({"label": "text", "text": text, "box": self._to_list(box),
                               "score": score, "block_order": line_index})
                lines.append(text)
                if score > 0:
                    numeric_scores.append(score)

            pages.append(
                {
                    "page_index": page_index,
                    "text": "\n".join(lines),
                    "score": sum(numeric_scores) / len(numeric_scores) if numeric_scores else 0.0,
                    "blocks": blocks,
                    "image_size": image_size,
                }
            )
            if lines:
                markdown_parts.append(f"[Page {page_index + 1}]\n" + "\n".join(lines))

        return {"pages": pages, "markdown": "\n\n".join(markdown_parts)}, raw_pages

    @staticmethod
    def _result_to_dict(item: object) -> dict[str, object]:
        if isinstance(item, dict):
            return dict(item)
        value = getattr(item, "json", None)
        try:
            value = value() if callable(value) else value
        except Exception:
            value = None
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except json.JSONDecodeError:
                value = None
        return dict(value) if isinstance(value, dict) else {}

    @staticmethod
    def _as_list(value: object) -> list[object]:
        if value is None:
            return []
        if hasattr(value, "tolist"):
            value = value.tolist()
        return list(value) if isinstance(value, (list, tuple)) else []

    @staticmethod
    def _to_list(value: object) -> list[object]:
        if hasattr(value, "tolist"):
            value = value.tolist()
        return list(value) if isinstance(value, (list, tuple)) else []

    @staticmethod
    def _as_float(value: object) -> float:
        try:
            return float(value) if value is not None else 0.0
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _as_int(value: object, default: int) -> int:
        try:
            return int(value) if value is not None else default
        except (TypeError, ValueError):
            return default
