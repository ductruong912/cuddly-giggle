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
    page_pairs = _pair_pages(primary.pages, fallback.pages)

    for p_page, f_page in page_pairs:
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


def _pair_pages(
    primary_pages: list[PageParseResult],
    fallback_pages: list[PageParseResult],
) -> list[tuple[PageParseResult | None, PageParseResult | None]]:
    # Align the two engines' pages by their physical page_index so a multi-page
    # document whose engines disagree on page count/order does not compare
    # unrelated pages. Fall back to positional pairing only if either engine has
    # duplicate/ambiguous indices (so no page is silently dropped).
    p_indices = [p.page_index for p in primary_pages]
    f_indices = [p.page_index for p in fallback_pages]
    if len(set(p_indices)) == len(primary_pages) and len(set(f_indices)) == len(fallback_pages):
        primary_by_index = {p.page_index: p for p in primary_pages}
        fallback_by_index = {p.page_index: p for p in fallback_pages}
        keys = sorted(set(primary_by_index) | set(fallback_by_index))
        return [(primary_by_index.get(k), fallback_by_index.get(k)) for k in keys]

    max_pages = max(len(primary_pages), len(fallback_pages))
    return [
        (
            primary_pages[idx] if idx < len(primary_pages) else None,
            fallback_pages[idx] if idx < len(fallback_pages) else None,
        )
        for idx in range(max_pages)
    ]


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
