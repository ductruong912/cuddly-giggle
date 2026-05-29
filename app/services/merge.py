from __future__ import annotations

from app.core.config import Settings, settings
from app.domain.schemas import Block, PageParseResult, Table
from app.services.engines.base import EngineParseResult


def merge_results(
    primary: EngineParseResult,
    fallback: EngineParseResult | None,
    app_settings: Settings = settings,
) -> EngineParseResult:
    if fallback is None:
        return primary

    merged_pages: list[PageParseResult] = []
    max_pages = max(len(primary.pages), len(fallback.pages))

    for idx in range(max_pages):
        p_page = primary.pages[idx] if idx < len(primary.pages) else None
        f_page = fallback.pages[idx] if idx < len(fallback.pages) else None

        if p_page is None and f_page is not None:
            merged_pages.append(f_page)
            continue
        if f_page is None and p_page is not None:
            merged_pages.append(p_page)
            continue
        if p_page is None or f_page is None:
            continue

        winner, loser = _pick_winner_by_confidence(
            primary_page=p_page,
            fallback_page=f_page,
            confidence_margin=app_settings.merge_fallback_confidence_margin,
        )

        # Merge in tables if winner has none or weaker table confidence.
        winner_tables = list(winner.tables)
        loser_tables = list(loser.tables)
        if _table_avg_confidence(winner_tables) < _table_avg_confidence(loser_tables):
            winner_tables = loser_tables

        # Keep block content from the page that preserves more recognized text.
        winner_blocks = list(winner.blocks)
        winner_order = list(winner.reading_order)
        winner_confidence = winner.confidence
        if _non_empty_blocks(loser.blocks) > _non_empty_blocks(winner.blocks):
            winner_blocks = list(loser.blocks)
            winner_order = list(loser.reading_order)
            # We are returning the loser's content, so the reported confidence must
            # reflect that content, not the (higher) winner's page score.
            winner_confidence = loser.confidence

        block_conf = _block_avg_confidence(winner_blocks)
        if winner_confidence <= 0.0 and block_conf > 0.0:
            winner_confidence = block_conf

        merged_pages.append(
            winner.model_copy(
                update={
                    "blocks": winner_blocks,
                    "reading_order": winner_order,
                    "confidence": winner_confidence,
                    "tables": winner_tables,
                    "source_engine": f"{p_page.source_engine}+{f_page.source_engine}",
                }
            )
        )

    markdown = _select_markdown(primary, fallback)

    return EngineParseResult(
        engine_name=f"{primary.engine_name}+{fallback.engine_name}",
        pages=merged_pages,
        markdown=markdown,
        raw={"primary": primary.raw, "fallback": fallback.raw},
    )


def _table_avg_confidence(tables: list[Table]) -> float:
    if not tables:
        return 0.0
    return sum(t.confidence for t in tables) / len(tables)


def _pick_winner_by_confidence(
    primary_page: PageParseResult,
    fallback_page: PageParseResult,
    confidence_margin: float,
) -> tuple[PageParseResult, PageParseResult]:
    if fallback_page.confidence >= primary_page.confidence + confidence_margin:
        return fallback_page, primary_page
    return primary_page, fallback_page


def _non_empty_blocks(blocks: list[Block]) -> int:
    return sum(1 for block in blocks if (block.content or "").strip())


def _block_avg_confidence(blocks: list[Block]) -> float:
    if not blocks:
        return 0.0
    return sum(block.confidence for block in blocks) / len(blocks)


def _select_markdown(primary: EngineParseResult, fallback: EngineParseResult) -> str | None:
    # Markdown is a single human-facing artifact. Fallback can enrich structured
    # table data, but appending both engine markdowns duplicates the document.
    if primary.markdown and primary.markdown.strip():
        return primary.markdown
    if fallback.markdown and fallback.markdown.strip():
        return fallback.markdown
    return None
