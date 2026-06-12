from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from statistics import median
from typing import Any

from app.core.config import Settings, settings
from app.domain.schemas import Block, BlockType, PageParseResult, Point, Table, TableCell
from app.services.engines.base import EngineParseResult, ParseEngine


_TCVN3_CHARS = "µ¸¶·¹¨»¾¼½Æ©ÇÊÈÉË®ÌÐÎÏÑªÒÕÓÔÖ×ÝØÜÞßãáâä«åèæçé¬êíëìîïóñòô\u00adõøö÷ùúýûüþ¡¢§£¤¥¦"
_UNICODE_CHARS = "àáảãạăằắẳẵặâầấẩẫậđèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵĂÂĐÊÔƠƯ"
_TCVN3_TRANSLATION = str.maketrans(dict(zip(_TCVN3_CHARS, _UNICODE_CHARS)))
_TCVN3_MARKERS = frozenset(_TCVN3_CHARS)


@dataclass(frozen=True)
class PdfWord:
    x0: float
    y0: float
    x1: float
    y1: float
    text: str

    @property
    def center_y(self) -> float:
        return (self.y0 + self.y1) / 2

    @property
    def height(self) -> float:
        return max(1.0, self.y1 - self.y0)


@dataclass(frozen=True)
class TextSegment:
    x0: float
    x1: float
    text: str


class PdfTextEngine(ParseEngine):
    name = "pdf_text"

    def __init__(self, app_settings: Settings = settings) -> None:
        self.settings = app_settings

    def parse(self, input_path: str, lang_hint: str = "auto") -> EngineParseResult:
        if Path(input_path).suffix.lower() != ".pdf":
            return EngineParseResult(engine_name=self.name, pages=[], markdown=None, raw={"reason": "not_pdf"})

        try:
            import fitz  # type: ignore
        except Exception as exc:
            raise RuntimeError("PyMuPDF is unavailable. Install PyMuPDF to parse text PDFs.") from exc

        doc = fitz.open(input_path)
        try:
            pages: list[PageParseResult] = []
            markdown_parts: list[str] = []
            raw_pages: list[dict[str, Any]] = []
            for page_index, page in enumerate(doc):
                text_dict = page.get_text("dict") or {}
                raw_blocks = text_dict.get("blocks", [])
                raw_words = _get_page_words(page)
                blocks = self._extract_page_blocks(raw_blocks, page_index)
                tables = _extract_tables_from_words(raw_words, page_index, self.settings.pdf_text_confidence)
                page_markdown = _build_layout_markdown(raw_words)
                if blocks:
                    markdown_parts.append(
                        page_markdown or "\n".join(block.content for block in blocks if block.content.strip())
                    )
                pages.append(
                    PageParseResult(
                        page_index=page_index,
                        blocks=blocks,
                        tables=tables,
                        reading_order=[block.block_id for block in blocks],
                        confidence=self.settings.pdf_text_confidence if blocks else 0.0,
                        source_engine=self.name,
                    )
                )
                raw_pages.append({"page_index": page_index, "blocks": raw_blocks, "words": raw_words})
        finally:
            doc.close()

        markdown = "\n\n".join(part for part in markdown_parts if part.strip()) or None
        return EngineParseResult(
            engine_name=self.name,
            pages=pages,
            markdown=markdown,
            raw={"pages": raw_pages},
        )

    def _extract_page_blocks(self, raw_blocks: object, page_index: int) -> list[Block]:
        if not isinstance(raw_blocks, list):
            return []

        blocks: list[Block] = []
        for block_index, raw_block in enumerate(raw_blocks):
            if not isinstance(raw_block, dict):
                continue
            if raw_block.get("type", 0) != 0:
                continue
            content = repair_legacy_vietnamese_text(_extract_block_text(raw_block))
            if not content:
                continue
            blocks.append(
                Block(
                    block_id=f"pdf_text_p{page_index}_b{block_index}",
                    type=BlockType.text,
                    content=content,
                    bbox=_bbox_to_polygon(raw_block.get("bbox")),
                    confidence=self.settings.pdf_text_confidence,
                    page_index=page_index,
                    source_engine=self.name,
                    extra={"block_order": block_index},
                )
            )
        return blocks


def repair_legacy_vietnamese_text(text: str) -> str:
    """Convert common TCVN3/ABC printer-PDF text into Unicode Vietnamese."""
    if not text:
        return text
    if not any(ch in _TCVN3_MARKERS for ch in text):
        return text
    return text.translate(_TCVN3_TRANSLATION)


def _get_page_words(page: object) -> list[object]:
    try:
        words = page.get_text("words")  # type: ignore[attr-defined]
    except Exception:
        return []
    return words if isinstance(words, list) else []


def _build_layout_markdown(raw_words: list[object]) -> str | None:
    lines = _group_words_into_lines(raw_words)
    if not lines:
        return None

    min_x = min(word.x0 for line in lines for word in line)
    rendered = [_format_layout_line(_segments_for_line(line), min_x) for line in lines]
    rendered = [line.rstrip() for line in rendered if line.strip()]
    if not rendered:
        return None
    return "```text\n" + "\n".join(rendered) + "\n```"


def _extract_tables_from_words(raw_words: list[object], page_index: int, confidence: float) -> list[Table]:
    rows: list[list[TextSegment]] = []
    for line in _group_words_into_lines(raw_words):
        segments = _segments_for_line(line)
        if len(segments) >= 3:
            rows.append(segments)

    if len(rows) < 2:
        return []

    cells: list[TableCell] = []
    for row_idx, row in enumerate(rows):
        for col_idx, segment in enumerate(row):
            cells.append(TableCell(row=row_idx, col=col_idx, text=segment.text, confidence=confidence))

    return [
        Table(
            table_id=f"pdf_text_tbl_p{page_index}_0",
            page_index=page_index,
            cells=cells,
            confidence=confidence,
        )
    ]


def _group_words_into_lines(raw_words: list[object]) -> list[list[PdfWord]]:
    words = _normalize_words(raw_words)
    if not words:
        return []

    y_tolerance = max(2.0, median(word.height for word in words) * 0.65)
    lines: list[list[PdfWord]] = []
    for word in sorted(words, key=lambda item: (item.center_y, item.x0)):
        if lines and abs(word.center_y - _line_center_y(lines[-1])) <= y_tolerance:
            lines[-1].append(word)
        else:
            lines.append([word])

    return [sorted(line, key=lambda item: item.x0) for line in lines]


def _segments_for_line(words: list[PdfWord]) -> list[TextSegment]:
    if not words:
        return []

    gap_threshold = max(12.0, median(word.height for word in words) * 1.25)
    segments: list[TextSegment] = []
    current_words = [words[0]]
    for word in words[1:]:
        gap = word.x0 - current_words[-1].x1
        if gap > gap_threshold:
            segments.append(_words_to_segment(current_words))
            current_words = [word]
        else:
            current_words.append(word)
    segments.append(_words_to_segment(current_words))
    return segments


def _format_layout_line(segments: list[TextSegment], min_x: float) -> str:
    line = ""
    for segment in segments:
        target_col = max(0, int(round((segment.x0 - min_x) / 6.0)))
        if line:
            line += " " * max(1, target_col - len(line))
        elif target_col:
            line += " " * target_col
        line += segment.text
    return line


def _normalize_words(raw_words: list[object]) -> list[PdfWord]:
    normalized: list[PdfWord] = []
    for raw_word in raw_words:
        if isinstance(raw_word, (list, tuple)) and len(raw_word) >= 5:
            try:
                x0, y0, x1, y1 = (float(raw_word[0]), float(raw_word[1]), float(raw_word[2]), float(raw_word[3]))
            except (TypeError, ValueError):
                continue
            text = repair_legacy_vietnamese_text(str(raw_word[4])).strip()
            if text:
                normalized.append(PdfWord(x0=x0, y0=y0, x1=x1, y1=y1, text=text))
    return normalized


def _line_center_y(words: list[PdfWord]) -> float:
    return sum(word.center_y for word in words) / len(words)


def _words_to_segment(words: list[PdfWord]) -> TextSegment:
    return TextSegment(
        x0=min(word.x0 for word in words),
        x1=max(word.x1 for word in words),
        text=" ".join(word.text for word in words),
    )


def is_pdf_text_result_usable(result: EngineParseResult, app_settings: Settings = settings) -> bool:
    if not result.pages:
        return False

    page_char_counts = [_useful_char_count("\n".join(block.content for block in page.blocks)) for page in result.pages]
    total_chars = sum(page_char_counts)
    text_pages = sum(1 for count in page_char_counts if count >= app_settings.pdf_text_min_chars_per_text_page)
    text_page_ratio = text_pages / len(result.pages)
    return (
        total_chars >= app_settings.pdf_text_min_total_chars
        and text_page_ratio >= app_settings.pdf_text_min_text_pages_ratio
    )


def _extract_block_text(raw_block: dict[str, Any]) -> str:
    lines = raw_block.get("lines")
    if not isinstance(lines, list):
        return ""

    text_lines: list[str] = []
    for line in lines:
        if not isinstance(line, dict):
            continue
        spans = line.get("spans")
        if not isinstance(spans, list):
            continue
        line_text = "".join(str(span.get("text", "")) for span in spans if isinstance(span, dict)).strip()
        if line_text:
            text_lines.append(line_text)
    return "\n".join(text_lines).strip()


def _bbox_to_polygon(raw_bbox: object) -> list[Point]:
    if not isinstance(raw_bbox, (list, tuple)) or len(raw_bbox) < 4:
        return []
    try:
        x1, y1, x2, y2 = (float(raw_bbox[0]), float(raw_bbox[1]), float(raw_bbox[2]), float(raw_bbox[3]))
    except (TypeError, ValueError):
        return []
    return [
        Point(x=x1, y=y1),
        Point(x=x2, y=y1),
        Point(x=x2, y=y2),
        Point(x=x1, y=y2),
    ]


def _useful_char_count(text: str) -> int:
    return len(re.sub(r"\s+", "", text or ""))