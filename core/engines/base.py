from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from core.domain.schemas import PageGeometry, PageParseResult


@dataclass
class EngineParseResult:
    engine_name: str
    pages: list[PageParseResult]
    markdown: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def page_confidence(self) -> float:
        if not self.pages:
            return 0.0
        return sum(page.confidence for page in self.pages) / len(self.pages)


class ParseEngine(ABC):
    name: str

    @abstractmethod
    def parse(self, input_path: str, lang_hint: str = "auto") -> EngineParseResult:
        raise NotImplementedError


def image_page_geometry(input_path: str, *, matches_original: bool) -> PageGeometry | None:
    """Read pixel dimensions lazily; unknown/EXIF-transformed images cannot be overlaid."""
    try:
        from PIL import Image

        with Image.open(input_path) as image:
            if image.getexif().get(274, 1) != 1 or getattr(image, "n_frames", 1) != 1:
                return None
            width, height = image.size
        return PageGeometry(
            width=width,
            height=height,
            coordinate_space="original" if matches_original else "processed",
        )
    except (ImportError, OSError, ValueError):
        return None
