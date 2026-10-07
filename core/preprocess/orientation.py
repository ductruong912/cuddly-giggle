"""Automatic 90-degree orientation normalization for scanned document pages."""
from __future__ import annotations

import threading
from typing import Any


_classifier: Any | None = None
_classifier_lock = threading.Lock()
_prediction_lock = threading.Lock()


def _get_classifier() -> Any:
    """Load the small orientation model once, on CPU, only when OCR needs it."""
    global _classifier
    if _classifier is None:
        with _classifier_lock:
            if _classifier is None:
                from paddleocr import DocImgOrientationClassification  # type: ignore

                _classifier = DocImgOrientationClassification(
                    model_name="PP-LCNet_x1_0_doc_ori",
                    device="cpu",
                )
    return _classifier


def warmup_orientation_classifier() -> None:
    """Load the classifier during explicit model setup, not on first production OCR."""
    _get_classifier()


def normalize_document_orientation(image: Any) -> tuple[Any, int]:
    """Rotate a page counterclockwise by the classifier's predicted correction angle.

    The four classifier labels are the correction angles (0, 90, 180, 270). A
    quarter-turn uses ``numpy.rot90`` so it does not resample or blur the page.
    """
    import numpy as np

    classifier = _get_classifier()
    with _prediction_lock:
        prediction = next(iter(classifier.predict(image, batch_size=1)), None)
    if prediction is None:
        raise RuntimeError("Document orientation classifier returned no prediction.")

    payload = prediction.json
    result = payload.get("res", payload) if isinstance(payload, dict) else None
    labels = result.get("label_names") if isinstance(result, dict) else None
    if not isinstance(labels, list) or not labels:
        raise RuntimeError("Document orientation classifier returned no orientation label.")

    try:
        angle = int(labels[0])
    except (TypeError, ValueError) as exc:
        raise RuntimeError("Document orientation classifier returned an invalid orientation label.") from exc
    if angle not in {0, 90, 180, 270}:
        raise RuntimeError(f"Document orientation classifier returned unsupported angle {angle}.")

    if angle == 0:
        return image, angle
    return np.rot90(image, k=angle // 90).copy(), angle
