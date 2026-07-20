from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from core.domain.schemas import PageParseResult


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
