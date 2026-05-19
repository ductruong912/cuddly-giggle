from __future__ import annotations

from app.core.config import Settings
from app.domain.schemas import Block, BlockType, PageParseResult, ParseOptions, Point
from app.services.engines.base import EngineParseResult, ParseEngine
from app.services.orchestrator import ParseOrchestrator


class StubEngine(ParseEngine):
    def __init__(self, name: str, confidence: float) -> None:
        self.name = name
        self._confidence = confidence

    def parse(self, input_path: str, lang_hint: str = "auto") -> EngineParseResult:
        page = PageParseResult(
            page_index=0,
            blocks=[
                Block(
                    block_id=f"b_{self.name}",
                    type=BlockType.text,
                    content="ngay 12-01-2026",
                    bbox=[Point(x=0, y=0)],
                    confidence=self._confidence,
                    page_index=0,
                    source_engine=self.name,
                )
            ],
            tables=[],
            reading_order=[f"b_{self.name}"],
            confidence=self._confidence,
            source_engine=self.name,
        )
        return EngineParseResult(engine_name=self.name, pages=[page], markdown="hello")


class FailingEngine(ParseEngine):
    name = "failing"

    def parse(self, input_path: str, lang_hint: str = "auto") -> EngineParseResult:
        raise RuntimeError("fallback engine crashed")


class ZeroScoreBlocksHighPageEngine(ParseEngine):
    name = "primary_high_page_conf"

    def parse(self, input_path: str, lang_hint: str = "auto") -> EngineParseResult:
        page = PageParseResult(
            page_index=0,
            blocks=[
                Block(
                    block_id="b_primary",
                    type=BlockType.text,
                    content="Noi dung hop le",
                    bbox=[Point(x=0, y=0)],
                    confidence=0.0,
                    page_index=0,
                    source_engine=self.name,
                )
            ],
            tables=[],
            reading_order=["b_primary"],
            confidence=0.9,
            source_engine=self.name,
        )
        return EngineParseResult(engine_name=self.name, pages=[page], markdown="ok")


def test_orchestrator_fallback_path() -> None:
    settings = Settings(
        confidence_pass_threshold=0.9,
        confidence_borderline_threshold=0.6,
        quality_fail_threshold=0.5,
    )
    orchestrator = ParseOrchestrator(
        app_settings=settings,
        primary_engine=StubEngine("primary", 0.55),
        fallback_engine=StubEngine("fallback", 0.8),
    )
    response = orchestrator.parse("tests/assets/doc.png", ParseOptions(enable_fallback=True))
    assert response.decision.status in {"borderline", "pass"}
    assert len(response.pages) == 1
    assert response.pages[0].source_engine in {"fallback", "primary+fallback"}


def test_orchestrator_fallback_failure_does_not_abort() -> None:
    settings = Settings(
        confidence_pass_threshold=0.9,
        confidence_borderline_threshold=0.6,
        quality_fail_threshold=0.5,
    )
    orchestrator = ParseOrchestrator(
        app_settings=settings,
        primary_engine=StubEngine("primary", 0.55),
        fallback_engine=FailingEngine(),
    )
    response = orchestrator.parse("tests/assets/doc.png", ParseOptions(enable_fallback=True))
    assert len(response.pages) == 1
    assert response.pages[0].source_engine == "primary"
    assert "Fallback skipped:" in response.decision.reason


def test_orchestrator_preserves_page_confidence_when_block_scores_are_zero() -> None:
    settings = Settings(
        confidence_pass_threshold=0.84,
        confidence_borderline_threshold=0.68,
        quality_fail_threshold=0.5,
    )
    orchestrator = ParseOrchestrator(
        app_settings=settings,
        primary_engine=ZeroScoreBlocksHighPageEngine(),
        fallback_engine=FailingEngine(),
    )
    response = orchestrator.parse("tests/assets/doc.png", ParseOptions(enable_fallback=True))
    assert response.decision.status == "pass"
    assert response.pages[0].confidence >= 0.84
