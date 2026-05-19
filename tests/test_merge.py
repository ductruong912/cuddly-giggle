from __future__ import annotations

from app.domain.schemas import Block, BlockType, PageParseResult, Point
from app.services.engines.base import EngineParseResult
from app.services.merge import merge_results


def _page(source: str, confidence: float, blocks: list[Block]) -> PageParseResult:
    return PageParseResult(
        page_index=0,
        blocks=blocks,
        tables=[],
        reading_order=[b.block_id for b in blocks],
        confidence=confidence,
        source_engine=source,
    )


def test_merge_keeps_non_empty_text_when_fallback_wins_confidence() -> None:
    primary_blocks = [
        Block(
            block_id="p1",
            type=BlockType.text,
            content="Co noi dung",
            bbox=[Point(x=0, y=0)],
            confidence=0.6,
            page_index=0,
            source_engine="primary",
        )
    ]
    fallback_blocks = [
        Block(
            block_id="f1",
            type=BlockType.text,
            content="",
            bbox=[Point(x=0, y=0)],
            confidence=0.95,
            page_index=0,
            source_engine="fallback",
        )
    ]

    primary = EngineParseResult(
        engine_name="primary",
        pages=[_page("primary", 0.6, primary_blocks)],
        markdown=None,
        raw={},
    )
    fallback = EngineParseResult(
        engine_name="fallback",
        pages=[_page("fallback", 0.95, fallback_blocks)],
        markdown=None,
        raw={},
    )

    merged = merge_results(primary, fallback)
    assert len(merged.pages) == 1
    assert merged.pages[0].blocks[0].content == "Co noi dung"


def test_merge_does_not_concatenate_primary_and_fallback_markdown() -> None:
    block = Block(
        block_id="p1",
        type=BlockType.text,
        content="Primary",
        bbox=[Point(x=0, y=0)],
        confidence=0.8,
        page_index=0,
        source_engine="primary",
    )
    primary = EngineParseResult(
        engine_name="primary",
        pages=[_page("primary", 0.8, [block])],
        markdown="## Primary markdown",
        raw={},
    )
    fallback = EngineParseResult(
        engine_name="fallback",
        pages=[_page("fallback", 0.7, [block.model_copy(update={"source_engine": "fallback"})])],
        markdown="## Fallback markdown",
        raw={},
    )

    merged = merge_results(primary, fallback)
    assert merged.markdown == "## Primary markdown"
    assert "---" not in (merged.markdown or "")
    assert "Fallback markdown" not in (merged.markdown or "")
