from __future__ import annotations

from app.core.config import Settings
from app.domain.schemas import Block, BlockType, PageParseResult, ParseOptions, Point, Table, TableCell
from app.services.engines.base import EngineParseResult, ParseEngine
from app.services.parsing.orchestrator import ParseOrchestrator


class StubEngine(ParseEngine):
    def __init__(
        self,
        name: str,
        confidence: float,
        content: str = "ngay 12-01-2026",
        tables: list[Table] | None = None,
    ) -> None:
        self.name = name
        self._confidence = confidence
        self._content = content
        self._tables = tables or []
        self.calls = 0

    def parse(self, input_path: str, lang_hint: str = "auto") -> EngineParseResult:
        self.calls += 1
        page = PageParseResult(
            page_index=0,
            blocks=[
                Block(
                    block_id=f"b_{self.name}",
                    type=BlockType.text,
                    content=self._content,
                    bbox=[Point(x=0, y=0)],
                    confidence=self._confidence,
                    page_index=0,
                    source_engine=self.name,
                )
            ],
            tables=self._tables,
            reading_order=[f"b_{self.name}"],
            confidence=self._confidence,
            source_engine=self.name,
        )
        return EngineParseResult(engine_name=self.name, pages=[page], markdown=self._content)


class FailingEngine(ParseEngine):
    def __init__(self, name: str = "failing", message: str = "engine crashed") -> None:
        self.name = name
        self.message = message

    def parse(self, input_path: str, lang_hint: str = "auto") -> EngineParseResult:
        raise RuntimeError(self.message)


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


def test_orchestrator_does_not_run_fallback_when_primary_succeeds() -> None:
    settings = Settings()
    fallback = StubEngine("fallback", 0.8)
    orchestrator = ParseOrchestrator(
        app_settings=settings,
        primary_engine=StubEngine("primary", 0.55),
        fallback_engine=fallback,
    )

    response = orchestrator.parse("tests/assets/doc.png", ParseOptions(enable_fallback=True))

    assert fallback.calls == 0
    assert response.decision.status == "pass"
    assert len(response.pages) == 1
    assert response.pages[0].source_engine == "primary"


def test_orchestrator_does_not_create_fallback_engine_when_primary_succeeds(monkeypatch) -> None:
    created_engines: list[str] = []

    def fake_create_engine(name: str, app_settings: Settings) -> ParseEngine:
        created_engines.append(name)
        return StubEngine("fallback", 0.8)

    monkeypatch.setattr("app.services.parsing.orchestrator.create_engine", fake_create_engine)
    orchestrator = ParseOrchestrator(
        app_settings=Settings(),
        primary_engine=StubEngine("primary", 0.9),
    )

    response = orchestrator.parse("tests/assets/doc.png", ParseOptions(enable_fallback=True))

    assert created_engines == []
    assert response.pages[0].source_engine == "primary"


def test_orchestrator_uses_fallback_when_primary_crashes_and_fallback_is_enabled() -> None:
    fallback = StubEngine("fallback", 0.8, "fallback text")
    orchestrator = ParseOrchestrator(
        app_settings=Settings(),
        primary_engine=FailingEngine("primary", "primary engine crashed"),
        fallback_engine=fallback,
    )

    response = orchestrator.parse("tests/assets/doc.png", ParseOptions(enable_fallback=True))

    assert fallback.calls == 1
    assert response.decision.status == "pass"
    assert "primary failed" in response.decision.reason.lower()
    assert response.pages[0].source_engine == "fallback"
    assert response.markdown == "fallback text"


def test_orchestrator_uses_fallback_on_primary_crash_by_default() -> None:
    fallback = StubEngine("fallback", 0.8, "fallback text")
    orchestrator = ParseOrchestrator(
        app_settings=Settings(),
        primary_engine=FailingEngine("primary", "primary engine crashed"),
        fallback_engine=fallback,
    )

    response = orchestrator.parse("tests/assets/doc.png", ParseOptions())

    assert fallback.calls == 1
    assert response.pages[0].source_engine == "fallback"
    assert response.markdown == "fallback text"


def test_orchestrator_raises_primary_error_when_fallback_is_disabled() -> None:
    fallback = StubEngine("fallback", 0.8)
    orchestrator = ParseOrchestrator(
        app_settings=Settings(),
        primary_engine=FailingEngine("primary", "primary engine crashed"),
        fallback_engine=fallback,
    )

    try:
        orchestrator.parse("tests/assets/doc.png", ParseOptions(enable_fallback=False))
    except RuntimeError as exc:
        assert "primary engine crashed" in str(exc)
    else:  # pragma: no cover - pytest assertion path
        raise AssertionError("Expected primary engine error to propagate.")
    assert fallback.calls == 0


def test_orchestrator_uses_pdf_text_engine_before_ocr_for_useful_text_pdf() -> None:
    settings = Settings(
        pdf_text_parse_enabled=True,
        pdf_text_min_total_chars=10,
        pdf_text_min_chars_per_text_page=5,
        pdf_text_min_text_pages_ratio=0.5,
    )
    pdf_text = StubEngine(
        "pdf_text",
        0.98,
        "Hoa don GTGT\nTong tien thanh toan 100000",
        tables=[
            Table(
                table_id="tbl_pdf_text",
                page_index=0,
                cells=[
                    TableCell(row=0, col=0, text="Ten san pham"),
                    TableCell(row=1, col=0, text="Banh quy"),
                ],
                confidence=0.98,
            )
        ],
    )
    primary = StubEngine("primary", 0.55, "ocr text")
    fallback = StubEngine("fallback", 0.8, "fallback text")
    orchestrator = ParseOrchestrator(
        app_settings=settings,
        primary_engine=primary,
        fallback_engine=fallback,
        pdf_text_engine=pdf_text,
    )

    response = orchestrator.parse("tests/assets/invoice.pdf", ParseOptions(enable_fallback=True))

    assert pdf_text.calls == 1
    assert primary.calls == 0
    assert fallback.calls == 0
    assert response.decision.status == "pass"
    assert response.pages[0].source_engine == "pdf_text"
    assert response.markdown == "Hoa don GTGT\nTong tien thanh toan 100000"


def test_orchestrator_falls_back_to_ocr_for_sparse_pdf_text_result() -> None:
    settings = Settings(
        pdf_text_parse_enabled=True,
        pdf_text_min_total_chars=80,
        pdf_text_min_chars_per_text_page=40,
        pdf_text_min_text_pages_ratio=0.5,
    )
    pdf_text = StubEngine("pdf_text", 0.98, "abc")
    primary = StubEngine("primary", 0.95, "ocr invoice text")
    fallback = StubEngine("fallback", 0.8, "fallback text")
    orchestrator = ParseOrchestrator(
        app_settings=settings,
        primary_engine=primary,
        fallback_engine=fallback,
        pdf_text_engine=pdf_text,
    )

    response = orchestrator.parse("tests/assets/invoice.pdf", ParseOptions(enable_fallback=True))

    assert pdf_text.calls == 1
    assert primary.calls == 1
    assert fallback.calls == 0
    assert response.pages[0].source_engine == "primary"
    assert response.markdown == "ocr invoice text"


def test_orchestrator_always_includes_markdown() -> None:
    settings = Settings(
        pdf_text_parse_enabled=True,
        pdf_text_min_total_chars=10,
        pdf_text_min_chars_per_text_page=5,
        pdf_text_min_text_pages_ratio=0.5,
    )
    pdf_text = StubEngine(
        "pdf_text",
        0.98,
        "Hoa don GTGT\nTong tien thanh toan 100000",
        tables=[
            Table(
                table_id="tbl_pdf_text",
                page_index=0,
                cells=[
                    TableCell(row=0, col=0, text="Ten san pham"),
                    TableCell(row=1, col=0, text="Banh quy"),
                ],
                confidence=0.98,
            )
        ],
    )
    primary = StubEngine("primary", 0.55, "ocr text")
    orchestrator = ParseOrchestrator(
        app_settings=settings,
        primary_engine=primary,
        fallback_engine=StubEngine("fallback", 0.8, "fallback text"),
        pdf_text_engine=pdf_text,
    )

    response = orchestrator.parse("tests/assets/invoice.pdf", ParseOptions(enable_fallback=True))

    assert primary.calls == 0
    assert response.markdown == "Hoa don GTGT\nTong tien thanh toan 100000"


def test_orchestrator_uses_word_text_engine_for_docx_without_ocr() -> None:
    settings = Settings()
    word_text = StubEngine("word_text", 0.99, "Phiếu đặt hàng")
    primary = StubEngine("primary", 0.95, "ocr text")
    fallback = StubEngine("fallback", 0.8, "fallback text")
    orchestrator = ParseOrchestrator(
        app_settings=settings,
        primary_engine=primary,
        fallback_engine=fallback,
        word_text_engine=word_text,
    )

    response = orchestrator.parse("tests/assets/order.docx", ParseOptions(enable_fallback=True))

    assert word_text.calls == 1
    assert primary.calls == 0
    assert fallback.calls == 0
    assert response.decision.status == "pass"
    assert response.pages[0].source_engine == "word_text"
    assert response.markdown == "Phiếu đặt hàng"


def test_orchestrator_uses_excel_text_engine_for_xlsx_without_ocr() -> None:
    settings = Settings()
    excel_text = StubEngine("excel_text", 0.99, "## Order\n\n| STT | Tên sản phẩm |\n| --- | --- |\n| 1 | COSY_Bánh quy |")
    primary = StubEngine("primary", 0.95, "ocr text")
    fallback = StubEngine("fallback", 0.8, "fallback text")
    orchestrator = ParseOrchestrator(
        app_settings=settings,
        primary_engine=primary,
        fallback_engine=fallback,
        excel_text_engine=excel_text,
    )

    response = orchestrator.parse("tests/assets/order.xlsx", ParseOptions(enable_fallback=True))

    assert excel_text.calls == 1
    assert primary.calls == 0
    assert fallback.calls == 0
    assert response.decision.status == "pass"
    assert response.pages[0].source_engine == "excel_text"
    assert "COSY_Bánh quy" in (response.markdown or "")


def test_orchestrator_does_not_call_failing_fallback_when_primary_succeeds() -> None:
    settings = Settings()
    orchestrator = ParseOrchestrator(
        app_settings=settings,
        primary_engine=StubEngine("primary", 0.55),
        fallback_engine=FailingEngine("fallback", "fallback engine crashed"),
    )
    response = orchestrator.parse("tests/assets/doc.png", ParseOptions(enable_fallback=True))
    assert len(response.pages) == 1
    assert response.pages[0].source_engine == "primary"
    assert response.decision.reason == "Parse completed."


def test_orchestrator_does_not_fail_parse_on_low_confidence_score() -> None:
    orchestrator = ParseOrchestrator(
        app_settings=Settings(),
        primary_engine=StubEngine("primary", 0.1, "ocr text"),
        fallback_engine=FailingEngine(),
    )

    response = orchestrator.parse("tests/assets/doc.png", ParseOptions(enable_fallback=False))

    assert response.decision.status == "pass"
    assert response.review_queued is False
    assert response.review_reason is None


def test_orchestrator_preserves_page_confidence_when_block_scores_are_zero() -> None:
    settings = Settings()
    orchestrator = ParseOrchestrator(
        app_settings=settings,
        primary_engine=ZeroScoreBlocksHighPageEngine(),
        fallback_engine=FailingEngine(),
    )
    response = orchestrator.parse("tests/assets/doc.png", ParseOptions(enable_fallback=True))
    assert response.decision.status == "pass"
    assert response.pages[0].confidence >= 0.84
